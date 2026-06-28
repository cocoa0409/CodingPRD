# Pet Wellness-Plan API — Product Requirements Document

## 1. Introduction

This document specifies the Pet Wellness-Plan Membership platform, a subscription system in the style of a veterinary "Optimum Wellness" program. Pet owners enrol their animals onto a tiered membership plan and, in exchange for a recurring monthly fee, receive a bundle of included preventive services — wellness exams, vaccinations, and dental cleanings — granted as a pool of pre-paid credits for each annual contract term. The platform must reconcile two very different views of value at all times: a *forward-looking* valuation of the entitlement granted when a term begins, and a *chronological* consumption ledger that debits those credits visit by visit in the order care is actually delivered. Where a service is not covered by a credit, the member is billed à-la-carte at a discounted, weight-sensitive price rather than the public-catalogue rate, which is the central distinction between a wellness plan and pet insurance: the plan pre-pays for routine prevention, it does not reimburse unpredictable illness.

The system is multi-pet and multi-clinic. A single account may carry several memberships, each membership may enrol several pets, and visits may be recorded at any open clinic, not only the member's home clinic. Membership operates on an annual contract with optional auto-renewal, so the design must handle renewal rounds that forfeit unused credits and grant a fresh bundle, mid-term plan upgrades and downgrades with daily-rate proration, pet removals, suspensions, and early cancellation with a settlement calculation. Because plan changes, renewals, billing runs, and cancellations all ripple across the pet roster, the credit ledger, the wallet, and the contract term simultaneously, the platform treats the membership as an aggregate root and reconciles its derived balances immediately after every mutating event. The remainder of this document defines the global contracts that all endpoints share, the business logic and lifecycle workflows that distinguish this domain, and the full endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API. The API is mounted under the `/wellness` path prefix.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting principal, and `X-User-Role`, which declares the capacity in which they are acting. If either header is missing or invalid, the request is rejected with `ERR_MISSING_AUTH_CONTEXT`. The system recognises exactly four roles, spelled precisely as `PlanAdmin`, `Member`, `ClinicStaff`, and `BillingAdmin`. When a role is authenticated but is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN_ROLE`.

The four roles divide cleanly by responsibility. A `PlanAdmin` owns the reference catalogue — the plans, the included-service inclusion lines, and the clinics — and may also advance the logical clock. A `Member` is an account holder who owns their own member account and the memberships hanging off it, performing the full self-service lifecycle of enrolment, suspension, resumption, plan change, pet management, and cancellation request. A `ClinicStaff` operator records and voids preventive-service visits. A `BillingAdmin` runs the monthly billing epoch, finalises pending cancellations, and may also advance the logical clock.

Role identity binds to resources differently per role. When `X-User-Role` is `Member`, `X-User-ID` is the `id` of the acting `MemberAccount`; ownership checks on any resource that references a `MemberAccount` compare the resource's owning-account foreign key to `X-User-ID`. Concretely, a `Member` acting on a membership or account must own it — that is, the `id` of the `MemberAccount` that owns the resource must equal `X-User-ID` — and a violation is rejected with `ERR_NOT_RESOURCE_OWNER`. When `X-User-Role` is `PlanAdmin`, `ClinicStaff`, or `BillingAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it for audit but does not compare it to any entity's `id`, and these three roles are not subject to per-owner ownership checks.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

---

### 2.3. Pagination

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip from the start of the result set and defaults to 0.

Unless a workflow states otherwise, all list endpoints return their resources sorted by creation timestamp (`created_at`) in ascending order. Every list response carries the pagination bookkeeping fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties and Logical Clock

Every primary resource carries a server-minted `id` formatted as a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC instant with three fractional digits. Most resources additionally carry an `updated_at` timestamp, refreshed on every mutation to the same ISO 8601 UTC format, and an integer `version` that begins at 1 (or the server's initial value) and increments by one on every mutation that changes the resource; this `version` is the basis for optimistic concurrency control described in §2.8. The entities that carry the full set — `id`, `created_at`, `updated_at`, and `version` — are `Plan`, `PlanService`, `Clinic`, `MemberAccount`, `Membership`, `EnrolledPet`, `ContractTerm`, `ServiceCredit`, `ServiceVisit`, `BillingCycle`, and `PlanChangeRequest`.

One entity is deliberately leaner. The `ClockState` resource carries only `id` and `created_at`; it has neither `updated_at` nor `version`, because it represents the platform's single logical clock rather than a business record. The clock exposes one field, `current_utc`. At server startup the logical clock reads exactly `2026-01-01T00:00:00Z` and never falls back to wall-clock time; until it is explicitly moved it holds that default. All time-dependent logic in the system — term start and end instants, pet enrolment timestamps, visit instants, billing windows, and renewal eligibility — reads this logical clock rather than the host machine's clock. Advancing the clock is a capability reserved to `PlanAdmin` and `BillingAdmin`, who supply the target instant in the `to_iso8601` field; applying it sets `current_utc` to that value. Reading the clock is available to all four roles.

### 2.5. Hierarchical Consistency and Cascades

The membership is an aggregate root, and many operations on it ripple down to its children and across to the ledger and wallet. Whenever a parent state change mandates a child state change — for example a membership suspension forcing each of its pets from `ENROLLED` to `SUSPENDED`, a resumption reversing exactly those pets back to `ENROLLED`, a cancellation request forfeiting open credit buckets, or a finalisation marking every pet `REMOVED` — the system performs the cascade automatically as part of the same operation, without requiring a separate request against each child. Each such cascade is a genuine mutation of the resources it touches: the affected resources have their `updated_at` refreshed, and resources that carry a `version` have it incremented, except where a specific workflow in §3 pins exactly which entity's `version` moves. Derived balances on the contract term — `entitlement_consumed_cents` and `entitlement_balance_cents` — are reconciled immediately after every event that can affect them, so a reader of the term always observes figures consistent with the underlying credit ledger.

### 2.6. Nested Resource Retrieval and Reference Validation

Many endpoints address a resource nested under a parent, such as a pet under a membership or a credit bucket under a contract term. For any path that contains more than one identifier, the system validates the identifiers left to right and rejects the request at the first identifier that does not resolve to an existing resource, returning `ERR_NOT_FOUND`. A request for a pet under a non-existent membership therefore fails on the membership before the pet is ever considered. Foreign keys supplied in a request body — for instance `plan_id`, `clinic_id`, `enrolled_pet_id`, or `to_plan_id` — are checked separately: when a body references an entity that does not exist, the request is rejected with `ERR_REFERENCE_NOT_FOUND`. The path-identifier check (`ERR_NOT_FOUND`) governs resources named in the URL; the body-reference check (`ERR_REFERENCE_NOT_FOUND`) governs foreign keys named in the payload.

### 2.7. Monetary Precision and Rounding

All monetary amounts in the system are integer cents, and every field whose name ends in `_cents` holds a whole number of cents. Most computations — entitlement valuation, chronological credit consumption, balance reconciliation, and monthly billing — are exact integer arithmetic with no rounding step at all. Two calculations involve a fractional intermediate and therefore pin a rounding rule explicitly: the à-la-carte discount and the plan-change proration. In both cases the rule is round half up to the nearest whole cent, and in both cases the document is precise about *when* the single rounding happens, because rounding at a different step can change the result by a cent. Those exact orderings are given inline in §3 where each calculation is described. The one non-integer input in the catalogue is a plan's à-la-carte discount, expressed as a fraction between 0.0 and 0.5 inclusive; it is applied as described in §3 and never stored as a monetary field.

### 2.8. Optimistic Concurrency Control on Plan Change

Changing a membership's plan is guarded by optimistic concurrency control to prevent a client from applying a change computed against a stale view of the membership. The plan-change operation requires a non-optional `expected_membership_version` field in its request body, carrying the `version` of the target `Membership` that the client last observed. If a prior plan-change has already taken effect — legitimately superseding the membership's `plan_id` and advancing its `version` — then a client still holding the older version is working from a stale `from_plan`, and its proration would be computed against the wrong starting plan. When `expected_membership_version` does not equal the membership's current `version`, the plan-change is rejected with `ERR_STALE_MEMBERSHIP_VERSION` at HTTP status 412. This is a stale-version comparison, not a timing or ordering rule. No other endpoint takes a version field; every operation other than plan change proceeds without an optimistic-concurrency check.

### 2.9. Validation Ordering

When several checks apply to one request, they are evaluated in a fixed priority order so that the returned error is deterministic. Authentication comes first: the presence and validity of the auth headers (`ERR_MISSING_AUTH_CONTEXT`) is checked before anything else, then the role's permission for the operation (`ERR_FORBIDDEN_ROLE`), then, for a `Member` acting on a membership or account, ownership of that resource (`ERR_NOT_RESOURCE_OWNER`). Existence checks follow: path identifiers are resolved left to right (`ERR_NOT_FOUND`), then body foreign keys are resolved (`ERR_REFERENCE_NOT_FOUND`). Only then are state and business rules evaluated: the target's state suitability for the requested transition (`ERR_INVALID_STATE` where no more specific state error applies), then the optimistic-concurrency version check on plan change (`ERR_STALE_MEMBERSHIP_VERSION`), then the domain-specific business rules. Among the business rules that share the visit-recording endpoint, the system checks that the pet belongs to the path membership (`ERR_PET_NOT_IN_MEMBERSHIP`), that the clinic is open (`ERR_CLINIC_CLOSED`), and that the pet is active (`ERR_PET_NOT_ACTIVE`), in that order. The plan-change business constraint (`ERR_INVALID_PLAN_CHANGE`) and the generic request-shape constraint (`ERR_INVALID_REQUEST`) guard their respective create and change operations, the e-mail uniqueness rule (`ERR_DUPLICATE_EMAIL`) guards account registration, and the term-window rule for visits (`ERR_VISIT_OUTSIDE_TERM`) guards visit recording.

## 3. Business Logic & Workflows

### 3.1. The Reference Catalogue: Plans, Inclusion Lines, and Clinics

Everything in the system rests on a catalogue maintained by a `PlanAdmin`. A **Plan** is created with a `tier` — one of `ESSENTIAL`, `PLUS`, or `PREMIUM` — a human-readable `name`, a recurring `monthly_fee_cents` of zero or more, and an `annual_value_cents` of zero or more that records the sticker value of the bundle for plan-versus-à-la-carte comparison. A plan may also specify an `alacarte_discount_pct`, the member's fractional discount on non-included services, which defaults to 0.0 and must lie between 0.0 and 0.5 inclusive, and an `enrollment_fee_cents`, a one-time fee charged the first time a pet is enrolled on the plan, which defaults to 0 and must be zero or more. A new plan begins life with `status` of `ACTIVE`; a `PlanAdmin` may later retire it, moving `status` from `ACTIVE` to `RETIRED`, after which it accepts no new enrolments. Plans are listed with optional filters on `status` and `tier`.

Each preventive service a plan includes is expressed as a **PlanService** inclusion line, created by a `PlanAdmin` against a parent plan referenced by `plan_id`. An inclusion line names a `service_code` — one of `EXAM`, `VACCINE`, or `DENTAL` — an `included_quantity` of credits granted per annual term (zero or more), and a `unit_value_cents` per-unit catalogue value of at least 1, used both for entitlement valuation and as the à-la-carte base price. An inclusion line starts `ACTIVE` and may be retired to `RETIRED`, which takes it out of future grants. Inclusion lines are listed with optional filters on `plan_id`, `service_code`, and `status`; filtering by `plan_id` is how a reader discovers which services a plan includes.

A **Clinic** is created by a `PlanAdmin` with a `name` and a `region_code` such as CA or TX; it opens with `status` of `OPEN` and may be closed, moving `status` from `OPEN` to `CLOSED`. Clinics are listed with optional filters on `status` and `region_code`. A closed clinic cannot host new visits, as covered in §3.5.

### 3.2. Member Accounts and Membership Creation

A prospective member first registers a **MemberAccount** by supplying a unique `email`, a `full_name`, and a `home_clinic_id` naming the default clinic for that member's pets. E-mail uniqueness is enforced case-insensitively: an attempt to register an address that already exists, regardless of letter case, is rejected with `ERR_DUPLICATE_EMAIL`. A freshly registered account opens with `status` of `ACTIVE` and a `wallet_credit_cents` balance of 0. The wallet is a refundable account-credit balance: fees debit it (and it may go negative), while cancellation settlements, plan-change downgrades, and visit-void refunds credit it back. A `Member` may list accounts filtered to their own by `email`, or by `home_clinic_id`; administrators may list all.

With an account in hand, a `Member` creates a **Membership** by supplying the owning `member_account_id`, the chosen `plan_id`, and a `billing_anchor_day` — the day of month on which the monthly fee is charged, which must be an integer from 1 to 28 inclusive. The member may also supply `auto_renew`, governing whether the active term rolls into a new one at expiry; it defaults to true. A new membership is created in `PENDING_PAYMENT` with no charge yet raised. At creation the system snapshots the plan's recurring fee into the membership's own `monthly_fee_cents` (the amount billed each epoch) and sets `pet_count` to 0. Throughout its life a membership exposes `pet_count`, a derived count of its `EnrolledPet` rows whose status is either `ENROLLED` or `SUSPENDED`. Memberships are listed with optional filters on `member_account_id`, `plan_id`, and `status`.

### 3.3. Enrolling Pets and Activating the Membership

While a membership is `PENDING_PAYMENT` or `ENROLLED`, a `Member` adds an **EnrolledPet** by supplying the pet's `name`, its `species` (`DOG` or `CAT`), and its `weight_kg`, which must be greater than zero and which later determines the dental surcharge tier. Adding a pet stamps the pet with an `enrolled_at` instant from the logical clock — this drives mid-term proration — sets its `status` to `ENROLLED`, recomputes the owning membership's `pet_count`, and increments the membership's `version` by one. Each pet records the `membership_id` of its owning membership. Pets under a membership are listed with an optional `status` filter, and a single pet is retrievable by its identifier.

A membership becomes live through activation, performed by the owning `Member`. Activation is permitted only from `PENDING_PAYMENT`; attempting it from any other status is rejected with `ERR_MEMBERSHIP_NOT_PENDING`. Activation additionally requires that at least one pet under the membership has status `ENROLLED`, failing which it is rejected with `ERR_NO_ENROLLED_PET`, and that the membership's plan is still `ACTIVE` rather than retired, failing which it is rejected with `ERR_PLAN_RETIRED`. When those conditions hold, activation moves the membership from `PENDING_PAYMENT` to `ENROLLED` and triggers a cascade of side effects. The system creates the first **ContractTerm** with `term_index` 1, `starts_at` set to the current logical-clock instant, `ends_at` set to exactly 365 days after `starts_at`, and `status` of `ACTIVE`. It grants the term's credit buckets by valuing the bundle forward (described in §3.4) and records the result on the term's `entitlement_granted_cents`, sets `entitlement_consumed_cents` to 0, and sets `entitlement_balance_cents` equal to the granted amount. It charges the wallet by debiting `wallet_credit_cents` by the plan's `enrollment_fee_cents` plus the first month's `monthly_fee_cents` (the debit may take the wallet negative). It creates the first **BillingCycle** with `status` of `BILLED` and `fee_charged_cents` equal to the monthly fee. It confirms the membership's `monthly_fee_cents` snapshot from the plan. Activation increments the membership's `version` by one.

Each contract term records the owning `membership_id`, the governing `plan_id` snapshot, its `term_index`, its `starts_at` and `ends_at` instants, and its three derived monetary figures. Contract terms and their credit buckets are read-only to clients and are listed with optional filters: terms by `membership_id`, `plan_id`, and `status`; the credit buckets of a term by `service_code` and `status`. Each **ServiceCredit** bucket records the `contract_term_id` that granted it, the `service_code` it covers, its `granted_quantity`, its running `consumed_quantity`, the `unit_value_cents` snapshot captured at grant time, and a `status` of `OPEN`, `EXHAUSTED`, or `FORFEITED`. A single bucket is also retrievable by its identifier.

### 3.4. Entitlement Valuation: Granting the Bundle Forward

When a term begins — at activation for the first term, and at each renewal for a successor term — the system values the bundle by looking forward over the catalogue. It considers only the `ACTIVE` inclusion lines of the term's plan, ordered by `service_code` ascending, and ignores any retired inclusion line. For each such line it creates one `ServiceCredit` bucket whose `granted_quantity` equals the line's `included_quantity`, whose `consumed_quantity` starts at 0, and whose `unit_value_cents` is a snapshot of the line's `unit_value_cents`; the bucket opens `OPEN` if the granted quantity is greater than zero and `EXHAUSTED` if the granted quantity is zero. The term's `entitlement_granted_cents` is the sum, over every created bucket, of that bucket's granted quantity multiplied by its unit value in cents; `entitlement_consumed_cents` is initialised to 0 and `entitlement_balance_cents` to the granted total. All of this is exact integer-cent arithmetic.

The forward valuation has two variants that differ only in *when* the catalogue is read. The enrolment grant seeds the buckets from the catalogue's currently-active inclusion lines as they stand at the enrolment instant. The renewal grant re-reads the catalogue at the renewal instant, which has a consequence worth stating plainly: an inclusion line that was retired at some point during the prior term is not re-granted on the successor term, because it is no longer `ACTIVE` when the successor is valued.

### 3.5. Recording Visits: Chronological Credit Consumption and À-la-carte Pricing

A `ClinicStaff` operator records a preventive-service visit against a membership by supplying the `enrolled_pet_id` of the pet seen, the `clinic_id` where the visit occurred, and the `service_code` rendered. The visit is stamped with a `visited_at` instant from the logical clock, which defines its place in the chronological consumption order, and it records the owning `membership_id`. The system resolves the membership's currently-`ACTIVE` contract term and records it on the visit's `contract_term_id`. A visit opens in `status` `COMPLETED`. Visits are listed with optional filters on `membership_id`, `enrolled_pet_id`, `clinic_id`, `contract_term_id`, `service_code`, and `status`, and a single visit is retrievable by its identifier.

Several guards apply before a visit is accepted, each surfacing its own error. The pet named by `enrolled_pet_id` must belong to the membership in the path — its `membership_id` must equal the path membership — or the request is rejected with `ERR_PET_NOT_IN_MEMBERSHIP`. The clinic must be `OPEN`, or the request is rejected with `ERR_CLINIC_CLOSED`. The pet must currently be `ENROLLED`, since suspended or removed pets cannot accrue visits, or the request is rejected with `ERR_PET_NOT_ACTIVE`. The system then resolves the membership's currently-`ACTIVE` contract term before checking the visit window: if the membership has no `ACTIVE` term to debit — for instance because it is not currently `ENROLLED` — the visit is rejected with `ERR_NO_ACTIVE_TERM`, and this active-term resolution is performed strictly before the window check. Only once an `ACTIVE` term has been resolved does the window check apply: the visit instant must fall inside that term's window, treated as inclusive of `starts_at` and exclusive of `ends_at`; a visit dated on or after the term end, or before the term start, is rejected with `ERR_VISIT_OUTSIDE_TERM`.

Consumption is chronological and order-dependent. A visit for a given service code consumes one matching credit unit if and only if, at the moment of recording, the bucket for that service code in the active term still has remaining capacity — that is, its `granted_quantity` minus its `consumed_quantity` is greater than zero. When capacity remains, the system increments that bucket's `consumed_quantity` by one; if the consumed quantity then equals the granted quantity, the bucket's `status` becomes `EXHAUSTED`; the visit's `covered_by_credit` is set to true and its `charged_cents` to 0. When no capacity remains, the visit's `covered_by_credit` is false and its `charged_cents` is the à-la-carte price computed below; in that case the à-la-carte charge debits the member's `wallet_credit_cents`. Stated as a boundary: the Nth visit of a service code is covered exactly when N is at most the granted quantity, and the very next visit after the bucket is full is billed à-la-carte. After applying the visit, the term's consumed and balance figures are reconciled as described in §3.7.

The à-la-carte price for an uncovered visit is built from three interacting inputs in a pinned order. The base is the `unit_value_cents` of the plan's inclusion line for that service code; here "has an inclusion line for that code" counts any line on the plan for that code regardless of its status, so a line that has since been retired still supplies the base (an `ACTIVE` line is preferred over a `RETIRED` one when both exist for the code). Only when the plan has no inclusion line at all for that code — for instance a plan that excludes `DENTAL` — does the base instead come from a catalogue default of 6000 cents for `EXAM`, 3500 cents for `VACCINE`, and 22000 cents for `DENTAL`. A surcharge applies only to dental visits and is driven by the pet's `weight_kg`: a pet weighing at least 25 kg adds a surcharge of 4000 cents, a pet weighing at least 10 kg but under 25 kg adds 1500 cents, and a lighter pet adds nothing; for non-dental services the surcharge is zero. The gross amount is the base plus the surcharge. The member discount is then applied with the rounding order pinned: first compute the discount as the gross multiplied by the plan's `alacarte_discount_pct` and round that product half up to a whole cent, then subtract the rounded discount from the gross to obtain `charged_cents`. The discount is rounded before the subtraction, not after; computing the charge as gross times one-minus-the-fraction and rounding at the end can differ by a cent and is not the rule.

A recorded visit may be voided by a `ClinicStaff` operator, which is a compensating action. Voiding is permitted only when the visit is `COMPLETED`, failing which it is rejected with `ERR_VISIT_NOT_VOIDABLE`, and only when the owning contract term is `ACTIVE`, failing which it is rejected with `ERR_TERM_NOT_ACTIVE_FOR_VOID`. A void moves the visit's `status` from `COMPLETED` to `VOIDED`. If the visit had been covered by a credit, the system restores one unit to the bucket it consumed by decrementing that bucket's `consumed_quantity` by one, and if the bucket had been full it moves from `EXHAUSTED` back to `OPEN`. If instead the visit had been billed à-la-carte, the system credits its `charged_cents` back to the member's `wallet_credit_cents`. Either way the term's consumed and balance figures are reconciled afterward.

### 3.6. Suspending, Resuming, Removing Pets, and Changing Plans

A `Member` may suspend an active membership to pause billing. Suspension is permitted only from `ENROLLED`, failing which it is rejected with `ERR_MEMBERSHIP_NOT_ENROLLED`. It moves the membership from `ENROLLED` to `SUSPENDED`, cascades every pet from `ENROLLED` to `SUSPENDED`, and increments the membership's `version` by one; while suspended, future billing cycles charge a `fee_charged_cents` of 0. The contract-term clock continues to run during suspension — the term is not extended — and existing credit buckets remain `OPEN`. Resumption reverses this and is permitted only from `SUSPENDED`, failing which it is rejected with `ERR_MEMBERSHIP_NOT_SUSPENDED`; it additionally requires that the contract term is still `ACTIVE` and that the current logical-clock instant is before the term's `ends_at`, failing which it is rejected with `ERR_TERM_EXPIRED`. Resumption moves the membership from `SUSPENDED` back to `ENROLLED`, cascades back to `ENROLLED` exactly those pets that the suspend action had suspended, resumes monthly billing at the next anchor day, and increments the membership's `version` by one.

A `Member` may remove a pet mid-term. Removal is permitted when the pet's status is `ENROLLED` or `SUSPENDED`, and an attempt to remove a pet already in any other state is rejected with `ERR_INVALID_STATE`. Removal moves the pet to `REMOVED`, recomputes the owning membership's `pet_count`, and increments the membership's `version` by one. (Pets are also moved to `REMOVED` as a cascade when a cancellation is finalised, as described in §3.8; that cascade does not by itself increment the membership's `version` through the per-pet rule — only the explicit member-initiated removal does.)

Changing the plan in force on a membership is a `Member` action guarded by the optimistic-concurrency rule of §2.8. The request supplies the `to_plan_id` of the target plan and the `expected_membership_version`. The target plan must differ from the membership's current plan and must itself be `ACTIVE`; a no-op target or a non-active target is rejected with `ERR_INVALID_PLAN_CHANGE`, and a retired target specifically is rejected with `ERR_PLAN_RETIRED`. When the change is accepted, the system records a **PlanChangeRequest** capturing the `membership_id`, the `from_plan_id` that was in force before the change, the `to_plan_id` target, a derived `change_kind`, and a derived signed `proration_delta_cents`. Although this records a new `PlanChangeRequest`, the operation is treated as an action upon the existing membership: it returns `200 OK` (not `201 Created`), and its `data` is the newly-recorded `PlanChangeRequest` object. The `change_kind` is `UPGRADE` when the target plan's monthly fee is greater than the current plan's monthly fee, and `DOWNGRADE` otherwise. The request opens with `status` `APPLIED`, and any prior `APPLIED` plan-change request on the same membership this cycle is superseded — its `status` moves to `SUPERSEDED`. Applying the change adjusts the wallet by the proration delta, updates the membership's `plan_id` and re-snapshots its `monthly_fee_cents`, and increments the membership's `version` by one. Plan-change requests are listed either under a specific membership, or across the system with optional filters on `membership_id`, `from_plan_id`, `to_plan_id`, and `status`, and a single request is retrievable by its identifier.

The proration is a daily-rate calculation over the current monthly billing window, with a single rounding at the very end. Let the number of days in the cycle be the count of days between the current cycle's `period_start` and `period_end`, counting the start day and not the end day, and let the days remaining be the count of days between the current logical-clock date and the cycle's `period_end`, which is never negative. The departing plan's daily rate is its monthly fee in cents divided by the days in the cycle as an exact rational (real division, not integer division), and the incoming plan's daily rate is its monthly fee divided by the same denominator. The proration delta is the incoming daily rate minus the departing daily rate, multiplied by the days remaining, computed as an exact rational and rounded half up to a whole number of cents exactly once at the end; rounding the two daily rates first and then multiplying can differ and is not the rule. A positive delta — the upgrade case — is an additional charge that debits the wallet now; a negative delta — the downgrade case — is a credit that adds its absolute value to the wallet now.

### 3.7. Balance Reconciliation

After every event that can touch the credit ledger — recording a visit, voiding a visit, a plan change, or a billing-epoch run — the system reconciles the owning contract term's derived balances so they always agree with the ServiceCredit ledger. The term's `entitlement_consumed_cents` is recomputed as the sum, over every credit bucket of that term regardless of its status, of the bucket's `consumed_quantity` multiplied by its `unit_value_cents`; this is exact integer-cent arithmetic. The term's `entitlement_balance_cents` is then the term's `entitlement_granted_cents` minus the freshly recomputed consumed total. Buckets that have been forfeited are still included in this sum: forfeiture only blocks further consumption, it does not erase consumption already recorded, so a `FORFEITED` bucket keeps its `consumed_quantity` and continues to contribute to the consumed total.

### 3.8. Cancellation and Early-Termination Settlement

A `Member` may cancel a membership early. Cancellation is permitted only when the membership is `ENROLLED` or `SUSPENDED`, failing which it is rejected with `ERR_MEMBERSHIP_NOT_CANCELLABLE`. Cancellation moves the membership from `ENROLLED` or `SUSPENDED` to `CANCEL_PENDING`, computes the early-termination settlement described below and records its credit on the wallet, sets `auto_renew` to false, marks the contract for termination at the end of the current cycle by moving the active contract term from `ACTIVE` to `TERMINATED`, forfeits every still-`OPEN` credit bucket on that term by moving each from `OPEN` to `FORFEITED` (whereupon the term's frozen balance is the basis for settlement), and increments the membership's `version` by one. Pet statuses are left unchanged at this stage and are only resolved at finalisation.

The settlement asks what the member is owed back on early cancel, on a gross basis. The value of credits already consumed is the term's `entitlement_consumed_cents`, with consumed credits valued at full catalogue unit value. The fees the member has paid are the sum of `fee_charged_cents` across all of this membership's billing cycles, plus the plan's `enrollment_fee_cents`. The unused value is the fees paid minus the consumed value, floored at zero so it is never negative. From that unused value an early-termination fee is taken, equal to the lesser of a flat 5000 cents and the unused value itself, so the fee never exceeds what is available. The settlement credit applied to the member's `wallet_credit_cents` is then the unused value minus the early-termination fee, again floored at zero. This gross basis — valuing consumed credits at full catalogue value — is the pinned rule; an alternative that valued consumed credits at the discounted à-la-carte price would yield a larger refund and is deliberately not used.

Finalising a cancellation is a `BillingAdmin` action that closes the membership out at cycle end. It is permitted only from `CANCEL_PENDING`, failing which it is rejected with `ERR_MEMBERSHIP_NOT_CANCEL_PENDING`. Finalisation moves the membership from `CANCEL_PENDING` to `CANCELLED`, cascades every remaining pet to `REMOVED`, and creates no further billing cycles for the membership. `CANCELLED` is the terminal state of the membership lifecycle.

### 3.9. The Billing Epoch: Monthly Charges and Annual Renewal

A `BillingAdmin` advances the platform forward by running the billing epoch, an administrative capability that processes both monthly charges and annual contract renewals against the current logical clock. Monthly billing applies to every membership whose `billing_anchor_day` equals the day-of-month of the current clock instant and whose status is `ENROLLED` or `SUSPENDED`, processed in `created_at` ascending order, deterministically and independent of resource identifier. For each such membership the system creates a `BillingCycle` with its `period_start` and `period_end` bounding the billed monthly period and `status` of `BILLED`. A membership that is `SUSPENDED` is charged a `fee_charged_cents` of 0; a membership that is `ENROLLED` is charged a `fee_charged_cents` equal to its snapshot `monthly_fee_cents`. Memberships in `PENDING_PAYMENT`, `CANCEL_PENDING`, or `CANCELLED` are skipped by monthly billing. The fee charged is debited from the member's `wallet_credit_cents`. A billing cycle also exposes a `proration_credit_cents` field nominally carrying any proration credit applied that cycle from a mid-term plan change or removal; in this implementation that field is always 0 — every billing cycle (the activation cycle and each monthly-epoch cycle) is created with `proration_credit_cents` of 0, because plan-change proration is settled directly against the wallet at the time of the change (§3.6) rather than recorded on a billing cycle, and pet removal applies no proration. Billing cycles are listed with optional filters on `membership_id` and `status`, and a single cycle is retrievable by its identifier. The billing-epoch endpoint always succeeds: it returns a `200 OK` list envelope (`response_type` of "array") whose `data` is the array of `BillingCycle` records created this epoch — in `created_at` ascending order — and whose `meta` carries `limit` equal to the number of cycles created, `offset` of 0, `total_count` equal to that same count, and `has_more` of false. When no membership is due for billing the epoch still succeeds with an empty `data` array rather than an error; the catalogued `ERR_NOT_DUE_FOR_BILLING` is never surfaced by this implementation.

The same epoch advances the annual contract lifecycle, which is cyclic across renewal rounds. A term that is `ACTIVE`, whose membership has `auto_renew` set to true, and for which the current clock instant has reached the point seven days before the term's `ends_at` (the renewal window), enters renewal by moving from `ACTIVE` to `RENEWAL_PENDING`; this merely flags the impending renewal and grants no credits yet. Once the clock instant reaches or passes the term's `ends_at`, a term in `RENEWAL_PENDING` expires: it moves from `RENEWAL_PENDING` to `EXPIRED`, every still-`OPEN` credit bucket on it is forfeited by moving to `FORFEITED` because unused credits do not roll over, and a successor term is created — its `term_index` is one greater than the expiring term's, its `starts_at` equals the expiring term's `ends_at`, its `ends_at` is 365 days later, and its `status` is `ACTIVE`. The successor term is granted a fresh set of credit buckets by the forward valuation of §3.4 (re-reading the catalogue at the renewal instant), and the renewal monthly fee is charged on the next billing cycle. After any of these epoch effects the affected term's balances are reconciled per §3.7. Both `EXPIRED` and `TERMINATED` are terminal states for a contract term.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource or add a new resource to a collection return a `201 Created` status code; operations that modify or act on an existing resource return a `200 OK` status code. All endpoints are mounted under the `/wellness` prefix shown in the paths below. Every request must carry the `X-User-ID` and `X-User-Role` headers described in §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/wellness/plans` | Create a plan in the catalogue | PlanAdmin |
| GET | `/wellness/plans` | List plans (filter by status, tier) | PlanAdmin, Member, ClinicStaff, BillingAdmin |
| GET | `/wellness/plans/{id}` | Get a plan | PlanAdmin, Member, ClinicStaff, BillingAdmin |
| POST | `/wellness/plans/{id}/retire` | Retire a plan | PlanAdmin |
| POST | `/wellness/plan-services` | Add an inclusion line to a plan | PlanAdmin |
| GET | `/wellness/plan-services` | List inclusion lines (filter by plan_id, service_code, status) | PlanAdmin, Member, ClinicStaff, BillingAdmin |
| GET | `/wellness/plan-services/{id}` | Get an inclusion line | PlanAdmin, Member, ClinicStaff, BillingAdmin |
| POST | `/wellness/plan-services/{id}/retire` | Retire an inclusion line | PlanAdmin |
| POST | `/wellness/clinics` | Create a clinic | PlanAdmin |
| GET | `/wellness/clinics` | List clinics (filter by status, region_code) | PlanAdmin, Member, ClinicStaff, BillingAdmin |
| GET | `/wellness/clinics/{id}` | Get a clinic | PlanAdmin, Member, ClinicStaff, BillingAdmin |
| POST | `/wellness/clinics/{id}/close` | Close a clinic | PlanAdmin |
| POST | `/wellness/member-accounts` | Register a member account | Member |
| GET | `/wellness/member-accounts` | List member accounts (members filter to own) | PlanAdmin, BillingAdmin, Member |
| GET | `/wellness/member-accounts/{id}` | Get a member account | Member, PlanAdmin, BillingAdmin |
| POST | `/wellness/memberships` | Create a membership in PENDING_PAYMENT | Member |
| GET | `/wellness/memberships` | List memberships (filter by member_account_id, plan_id, status) | PlanAdmin, BillingAdmin, Member |
| GET | `/wellness/memberships/{id}` | Get a membership | Member, PlanAdmin, BillingAdmin |
| POST | `/wellness/memberships/{id}/pets` | Add an enrolled pet | Member |
| GET | `/wellness/memberships/{id}/pets` | List pets under a membership | Member, PlanAdmin, BillingAdmin, ClinicStaff |
| GET | `/wellness/memberships/{id}/pets/{petId}` | Get one enrolled pet | Member, PlanAdmin, BillingAdmin, ClinicStaff |
| POST | `/wellness/memberships/{id}/pets/{petId}/remove` | Remove a pet mid-term | Member |
| POST | `/wellness/memberships/{id}/activate` | Activate the membership | Member |
| POST | `/wellness/memberships/{id}/suspend` | Suspend the membership | Member |
| POST | `/wellness/memberships/{id}/resume` | Resume a suspended membership | Member |
| POST | `/wellness/memberships/{id}/plan-change` | Change plan with proration (OCC-guarded) | Member |
| GET | `/wellness/memberships/{id}/plan-changes` | List a membership's plan-change requests | Member, PlanAdmin, BillingAdmin |
| GET | `/wellness/plan-changes` | List plan-change requests (filter by membership_id, from_plan_id, to_plan_id, status) | PlanAdmin, BillingAdmin, Member |
| GET | `/wellness/plan-changes/{id}` | Get a plan-change request | PlanAdmin, BillingAdmin, Member |
| POST | `/wellness/memberships/{id}/cancel` | Member-initiated early cancellation | Member |
| POST | `/wellness/memberships/{id}/finalize-cancel` | Finalize cancellation at cycle end | BillingAdmin |
| GET | `/wellness/contract-terms` | List contract terms (filter by membership_id, plan_id, status) | Member, PlanAdmin, BillingAdmin |
| GET | `/wellness/contract-terms/{id}` | Get a contract term | Member, PlanAdmin, BillingAdmin |
| GET | `/wellness/contract-terms/{id}/credits` | List a term's credit buckets | Member, PlanAdmin, BillingAdmin |
| GET | `/wellness/service-credits/{id}` | Get a single credit bucket | Member, PlanAdmin, BillingAdmin |
| POST | `/wellness/memberships/{id}/visits` | Record a preventive-service visit | ClinicStaff |
| GET | `/wellness/visits` | List visits (filter by membership_id, enrolled_pet_id, clinic_id, contract_term_id, service_code, status) | Member, PlanAdmin, BillingAdmin, ClinicStaff |
| GET | `/wellness/visits/{id}` | Get a visit | Member, PlanAdmin, BillingAdmin, ClinicStaff |
| POST | `/wellness/visits/{id}/void` | Void a recorded visit | ClinicStaff |
| GET | `/wellness/billing-cycles` | List billing cycles (filter by membership_id, status) | Member, PlanAdmin, BillingAdmin |
| GET | `/wellness/billing-cycles/{id}` | Get a billing cycle | Member, PlanAdmin, BillingAdmin |
| POST | `/wellness/_billing/run-epoch` | Advance the monthly billing epoch and run renewals | BillingAdmin |
| POST | `/wellness/_clock/set_current_utc` | Set the logical clock | BillingAdmin, PlanAdmin |
| GET | `/wellness/_clock` | Read the logical clock | BillingAdmin, PlanAdmin, Member, ClinicStaff |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_AUTH_CONTEXT` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_MEMBERSHIP_NOT_PENDING` | 409 Conflict |
| `ERR_NO_ENROLLED_PET` | 409 Conflict |
| `ERR_PLAN_RETIRED` | 409 Conflict |
| `ERR_MEMBERSHIP_NOT_ENROLLED` | 409 Conflict |
| `ERR_MEMBERSHIP_NOT_SUSPENDED` | 409 Conflict |
| `ERR_MEMBERSHIP_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_MEMBERSHIP_NOT_CANCEL_PENDING` | 409 Conflict |
| `ERR_TERM_EXPIRED` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_INVALID_PLAN_CHANGE` | 422 Unprocessable Entity |
| `ERR_STALE_MEMBERSHIP_VERSION` | 412 Precondition Failed |
| `ERR_PET_NOT_IN_MEMBERSHIP` | 409 Conflict |
| `ERR_PET_NOT_ACTIVE` | 409 Conflict |
| `ERR_CLINIC_CLOSED` | 409 Conflict |
| `ERR_VISIT_OUTSIDE_TERM` | 409 Conflict |
| `ERR_NO_ACTIVE_TERM` | 409 Conflict |
| `ERR_VISIT_NOT_VOIDABLE` | 409 Conflict |
| `ERR_TERM_NOT_ACTIVE_FOR_VOID` | 409 Conflict |
| `ERR_NOT_DUE_FOR_BILLING` | 409 Conflict |
