# Structured Settlement Annuity API — Product Requirements Document

## 1. Introduction

When a personal-injury or wrongful-death claim resolves as a structured settlement, the defendant's obligation to pay a stream of periodic payments is typically assigned — under IRC Section 130 — to a qualified assignment company, which funds the stream by purchasing a single-premium annuity from a life insurer. The issuer of that annuity then administers the payment stream for years, often decades: maintaining schedules and cost-of-living escalations, issuing checks and electronic transfers, investigating returned payments, honoring guardianship orders for minor payees, supervising secondary-market transfers through the courts, and reporting dormant property to the states. This document specifies the Structured Settlement Annuity API, mounted under `/annuity`, which serves as the system of record for that administration.

The API spans the full administrative lifecycle: per-state statutory profiles encoding each jurisdiction's Structured Settlement Protection Act constraints; payee registration with minority evaluation; settlement agreement, qualified assignment, and annuity policy setup; payment schedule authoring with pinned escalation arithmetic; issuance, clearing, return, and reissue of individual payments; payee change requests under segregation-of-duties review; transfer petitions with statutory disclosure, cooling-off, and court-approval gates; death claims with certain-period treatment; commutations; and dormancy-driven escheatment with owner reclaim. Every time-dependent rule is evaluated against a controllable logical clock (§2.4) rather than wall-clock time, every response flows through a single envelope (§2.2), and the two workflows most exposed to stale reads — schedule activation and commutation creation — are guarded by optimistic concurrency control (§2.7).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the caller's operational capacity. The declared roles are `PlatformAdmin`, `CaseManager`, `OperationsSpecialist`, `ComplianceOfficer`, `JudicialRecorder`, `Payee`, and the read-only umbrella role `Any` under which every authenticated caller may use the list and single-read endpoints. A request missing either header, or presenting a role string outside this list, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is well-formed but not authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

Identity semantics differ by role, and the difference is load-bearing. When `X-User-Role` is `Payee`, `X-User-ID` is the `id` of the acting `Payee`; ownership checks on any resource that references a payee compare the resource's payee foreign key to `X-User-ID`. Concretely, a payee submitting a change request must pass their own id as `payee_id`, a payee drafting a transfer petition must pass their own id as `payee_id`, and a payee filing or withdrawing a petition must be the petition's payee — a mismatch on any of these is `ERR_FORBIDDEN_ROLE`. When `X-User-Role` is `PlatformAdmin`, `CaseManager`, `OperationsSpecialist`, `ComplianceOfficer`, `JudicialRecorder`, or `Any`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it — for example as `opened_by_user_id` on a returned-payment case or an escheatment batch, as `submitted_by_user_id` on a change request, as `filed_by_user_id` on a petition, or as `order_recorded_by_user_id` when a court order is recorded — but does not compare it to any entity's `id`. Those recorded identifiers are the anchors for the segregation-of-duties rules in §2.9.

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

A request that matches no defined path — or a defined path with an unsupported method — is answered with `ERR_NOT_FOUND` (HTTP 404). A request body that is not a JSON object is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

---

### 2.3. Pagination

List endpoints paginate through two query parameters. The `limit` parameter sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. A non-integer or out-of-range value for either parameter is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation order. The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. The Logical Clock

Every time-dependent rule in this API — payment maturation, check staling, dormancy, guardianship auto-termination, petition expiry — is evaluated against a server-side logical clock, never against wall-clock time. Before any clock-setting call has been made, the clock reads exactly 2026-08-01T00:00:00Z. A `PlatformAdmin`-only, test-driving capability sets the clock to a supplied `to_iso8601` instant — any ISO 8601 timestamp, ahead of or behind the current reading, with a missing offset read as UTC; the response reports the new `current_utc` and a `transitions_fired` count of how many system transitions the sweep fired.

Each clock-set runs a system sweep whose steps execute in a pinned order:

1. Guardianship auto-termination — `ACTIVE` guardianship cases whose payee has reached the residence profile's `age_of_majority` terminate (§3.1).
2. Payment maturation — `SCHEDULED` payments on an `ACTIVE` schedule whose agreement is `FUNDED` or `ACTIVE`, and whose `due_date` is on or before the clock date, become `PAYABLE` (§3.3).
3. Agreement activation — an agreement still `FUNDED` when step 2 produced its first `PAYABLE` payment becomes `ACTIVE` (§3.2).
4. Check staling — `ISSUED` checks more than 180 days old become `STALE_DATED` (§3.4).
5. Dormancy — payments in `ISSUED`, `STALE_DATED`, or `RETURNED` past their dormancy anniversary become `ESCHEATABLE` (§3.8).
6. Petition expiry — `COURT_APPROVED` petitions more than 60 days past their `court_order_date` without effectuation become `EXPIRED` (§3.6).

Ordering is observable behavior. Because step 4 runs before step 5 within a single sweep, one clock-set can carry a payment from `ISSUED` through `STALE_DATED` to `ESCHEATABLE`; conversely, a petition expiring in step 6 has no retroactive effect on the payments matured in step 2.

### 2.5. Common Resource Properties

Every resource in this API — statute profiles, payees, guardianship cases, agreements, assignments, policies, schedules, payments, returned-payment cases, change requests, petitions, death claims, commutation requests, and escheatment batches — carries the same four system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer, starting at 1 when the resource is created, that increments on every mutation, including cascaded transitions and ledger recomputations triggered by another resource's change.

The `version` field is the foundation of the optimistic-concurrency contract in §2.7: clients read it, and the two guarded write endpoints require the client to present the value they last observed.

### 2.6. Monetary Precision, Rates, and Rounding

All money in the API is represented as integer cents — `amount_cents`, `premium_cents`, `purchase_price_cents`, the agreement ledger totals, and so on — and all rates are expressed in integer basis points, where ten thousand basis points equal one hundred percent. Every rounding in the system rounds half up: to the nearest whole cent for money, and to the nearest whole basis point for rate outputs. Two workflows discount streams of future payments, and both pin the rounding order — each payment's discounted value is rounded half up to whole cents first, and only then are the per-payment values summed. Summing unrounded values and rounding once at the end can differ by one or more cents and is not the contract (§3.6, §3.7). Date fields use the YYYY-MM-DD form unless a endpoint states otherwise; the escheatment batch's reporting label uses YYYY-MM. Anniversary arithmetic — escalation anniversaries, majority birthdays, and dormancy anniversaries — keeps the month and day, mapping February 29 to February 28 in non-leap years.

### 2.7. Optimistic Concurrency Control

Exactly two write endpoints participate in optimistic concurrency control, and each takes a non-optional version field carrying the client's last-observed `version` of the parent aggregate.

Activating a payment schedule supersedes whichever schedule is currently `ACTIVE` for the agreement and rewires the agreement's payment population, so the activation request must carry `expected_settlement_agreement_version` equal to the agreement's current `version`. If the agreement's version has advanced since the client last read it — an intervening activation, a payment transition that recomputed ledger totals, a status change — the activation is rejected with `ERR_STALE_AGREEMENT_VERSION` (HTTP 412), forcing the client to re-read the agreement and re-issue rather than overwrite a payment population it never observed.

Creating a commutation request mutates the policy: creation itself advances the policy's `version`, and repeated partial commutations keep shrinking the remaining payment population. The creation request must therefore carry `expected_annuity_policy_version` equal to the policy's current `version`; a mismatch is rejected with `ERR_STALE_POLICY_VERSION` (HTTP 412) and the client must re-read the policy before retrying. No endpoint other than these two accepts a version field.

### 2.8. Statutory Profiles as the Jurisdictional Oracle

Structured-settlement law varies by state, so the API externalizes every jurisdictional constant into the `StateStatuteProfile` resource rather than hard-coding it. Which profile governs depends on the workflow: minority and dormancy evaluations key off the payee's `address_state_code`; a transfer petition's rate cap, cooling-off period, and advice requirement key off the petition's `state_code`, captured from the payee's residence at filing; and a commutation's discount rate is the lesser of the policy's pricing rate and the primary payee's residence profile's cap. Any state code that fails to resolve to a registered profile — a payee's `address_state_code`, an agreement's `court_state_code`, or a change request's `new_address_state_code` — fails the request with `ERR_STATE_PROFILE_NOT_FOUND` (HTTP 404). Registering a second profile for a state code that already has one fails with `ERR_DUPLICATE_STATE_PROFILE` (HTTP 409).

### 2.9. Segregation of Duties

Four operations enforce segregation of duties by comparing the caller's `X-User-ID` against an operator identifier recorded on the resource at an earlier step; every violation is rejected with `ERR_SOD_VIOLATION` (HTTP 403).

- The operations specialist authorizing reissue of a returned payment must not be the user who reported the return — the case's `opened_by_user_id`.
- The compliance officer finalizing an escheatment batch must not be the user who opened it — the batch's `opened_by_user_id`.
- The judicial recorder recording a petition's court order must not be the user who filed the petition — the petition's `filed_by_user_id`.
- The compliance officer approving a payee change request must not be the user who submitted it — the request's `submitted_by_user_id`.

### 2.10. Validation Precedence

Every request is validated in a fixed global order, and the first failing check determines the error returned:

1. Header presence and role validity — `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. Role authorization for the endpoint, including payee self-service ownership — `ERR_FORBIDDEN_ROLE`.
3. Existence: path identifiers are validated left to right, then body-referenced identifiers (`payee_id`, `settlement_agreement_id`, and the like) must resolve — `ERR_NOT_FOUND` (HTTP 404); state codes that must reference a statutory profile are resolved here as well — `ERR_STATE_PROFILE_NOT_FOUND`.
4. Optimistic-concurrency version checks, where §2.7 applies — `ERR_STALE_AGREEMENT_VERSION` or `ERR_STALE_POLICY_VERSION`. These run after existence and before every state or business guard.
5. Target-entity state guards: the resource must be in the state its transition requires — the per-machine family `ERR_AGREEMENT_INVALID_STATE`, `ERR_ASSIGNMENT_INVALID_STATE`, `ERR_POLICY_INVALID_STATE`, `ERR_SCHEDULE_INVALID_STATE`, `ERR_CASE_INVALID_STATE`, `ERR_CHANGE_REQUEST_INVALID_STATE`, `ERR_PETITION_INVALID_STATE`, `ERR_CLAIM_INVALID_STATE`, `ERR_COMMUTATION_INVALID_STATE`, `ERR_BATCH_INVALID_STATE`, `ERR_GUARDIANSHIP_INVALID_STATE`, and the payment-state errors `ERR_PAYMENT_NOT_PAYABLE`, `ERR_PAYMENT_NOT_ISSUED`, `ERR_PAYMENT_NOT_RETURNED`, `ERR_PAYMENT_NOT_ESCHEATED` (all HTTP 409).
6. Business guards, in their own relative order: guardianship presence for a minor payee (`ERR_GUARDIANSHIP_REQUIRED`); commutation legality (`ERR_COMMUTATION_NOT_PERMITTED`); segregation of duties (`ERR_SOD_VIOLATION`); the SSPA effective-rate cap (`ERR_EFFECTIVE_RATE_EXCEEDS_CAP`); the disclosure cooling-off period (`ERR_COOLING_OFF_NOT_ELAPSED`); independent professional advice (`ERR_IPA_REQUIRED`); the with-prejudice refile bar (`ERR_REFILE_BARRED_WITH_PREJUDICE`); dormancy (`ERR_DORMANCY_NOT_MET`); transfer-window overlap (`ERR_TRANSFER_WINDOW_OVERLAP`); guardianship-interval overlap (`ERR_GUARDIANSHIP_OVERLAP`); uniqueness (`ERR_DUPLICATE_CASE_NUMBER`, `ERR_DUPLICATE_STATE_PROFILE`, `ERR_OPEN_BATCH_EXISTS`); non-empty selection (`ERR_NO_TRANSFERRABLE_PAYMENTS`, `ERR_NO_COMMUTABLE_PAYMENTS`); open-batch presence for a reclaim (`ERR_NO_OPEN_ESCHEAT_BATCH`); cross-entity state requirements (for example an agreement or assignment gating a downstream creation, or a death claim gating a `DEATH` commutation); and price sanity (`ERR_PRICE_EXCEEDS_PRESENT_VALUE`).
7. Input shape last: required fields present, enum members valid, date strings in the required form, cents fields positive where required, a payment's `due_date` not earlier than its schedule's `effective_from_date`, `transfer_end_date` not earlier than `transfer_start_date`, and no unknown payload fields — all rejected as `ERR_INVALID_REQUEST` (HTTP 400). Shape checks run after existence, state, and business guards so that a request failing a domain rule surfaces the domain error rather than a shape error. Action endpoints that define no request fields perform no field validation: a JSON object body carrying unknown fields is accepted and ignored (a body that is not a JSON object is still `ERR_INVALID_REQUEST`).

## 3. Business Logic & Workflows

### 3.1. Statutory Profiles, Payee Registration, and Guardianship

Before any payee or agreement can reference a jurisdiction, a `PlatformAdmin` registers a `StateStatuteProfile` for it. The profile carries the two-letter uppercase `state_code`, unique across profiles; `age_of_majority`, the age at which a payee ceases to be a minor, from 18 to 21 inclusive; `sspa_max_discount_rate_bps`, the state's Structured Settlement Protection Act cap on a transfer petition's effective annual rate, strictly positive; `disclosure_cooling_off_days`, the minimum whole days that must elapse between disclosure service and hearing scheduling, with zero allowed; `ipa_required`, whether the state requires independent professional advice before a transfer hearing may be scheduled; `dormancy_years`, the unclaimed-property dormancy period, at least one year; and `commutation_permitted`, whether the state permits commutation of structured settlement payments at all. Profiles may be listed by any caller, optionally filtered by `state_code`, or read individually.

A `CaseManager` registers each injured party as a `Payee` with `full_name`, `date_of_birth` (strictly before the current clock date), `tax_id` for 1099 reporting, and a mailing address split across `address_line1`, `address_city`, `address_state_code`, and `address_postal_code`; `phone` and `email` are optional. The `address_state_code` selects the profile used for minority and dormancy evaluation, so it must resolve to a registered profile. A new payee starts `ACTIVE` with `deceased_date` null. The computed flag `is_minor` is evaluated against the current logical clock on every read: the payee's age is measured in whole years, subtracting one when the birthday has not yet occurred this calendar year, and `is_minor` is true exactly when that age is strictly less than the residence profile's `age_of_majority` — on the majority birthday itself the payee is no longer a minor. Payees may be listed filtered by `status` or `address_state_code`.

When a court appoints a guardian or conservator, a `CaseManager` opens a `GuardianshipCase` naming the protected payee via `payee_id`, the appointing court's state as `court_state_code`, the `guardian_full_name` — the name payments to a minor are made payable to — and `effective_from_date`, the inclusive first day of guardianship authority. Cases begin `PENDING_REVIEW` and are activated by a `ComplianceOfficer` once the court order is reviewed: `PENDING_REVIEW` → `ACTIVE`, with `ERR_GUARDIANSHIP_INVALID_STATE` greeting an activation attempt on a case in any other state. Guardianship intervals are half-open — a case governs from `effective_from_date` up to but not including `terminated_at_date`, which is null while the appointment is open-ended and is then treated as infinity. Both at creation and again at activation, the system rejects overlap with `ERR_GUARDIANSHIP_OVERLAP` when any other `PENDING_REVIEW` or `ACTIVE` case for the same payee has an interval intersecting the new case's interval. Revocation by a `ComplianceOfficer` requires an `ACTIVE` case (`ERR_GUARDIANSHIP_INVALID_STATE` otherwise) and moves it `ACTIVE` → `REVOKED`, stamping `terminated_at_date` with the current clock date.

Two system events close an active guardianship without operator action. On every clock-set, a payee who has reached the residence profile's `age_of_majority` — the clock date on or after the majority birthday — has the case moved `ACTIVE` → `TERMINATED` with `terminated_at_date` set to the majority birthday itself; a case whose `effective_from_date` is on or after the majority birthday — a guardianship established over an adult — does not auto-terminate. Separately, settlement of a death claim for the protected payee terminates the case with `terminated_at_date` set to the claim's `date_of_death` (§3.7). Cases may be listed filtered by `payee_id` or `status`.

### 3.2. Structuring the Settlement: Agreement, Assignment, and Annuity Purchase

A structured settlement engagement begins when a `CaseManager` creates a `SettlementAgreement` with a unique `case_number` — a duplicate fails with `ERR_DUPLICATE_CASE_NUMBER` — the settling court's `court_state_code`, which must resolve to a registered profile; the `obligor_name` of the defendant or insurer obligated to fund the settlement; the `injury_type`, either `PHYSICAL` for awards tax-free under IRC 104(a)(2) or `NON_PHYSICAL` for taxable awards; the injured party's `primary_payee_id`; and the `agreement_date`. The agreement starts `DRAFT` with all six ledger totals — `total_scheduled_cents`, `outstanding_liability_cents`, `paid_total_cents`, `escheated_total_cents`, `transferred_total_cents`, and `commuted_nominal_total_cents` — at zero. Agreements may be listed filtered by `status`, `court_state_code`, or `primary_payee_id`, and a single read returns the ledger totals alongside the current `version`.

Execution by a case manager moves the agreement `DRAFT` → `EXECUTED` and bumps its `version`; attempting execution from any other state fails with `ERR_AGREEMENT_INVALID_STATE`. The IRC Section 130 qualified assignment follows: creating a `QualifiedAssignment` — supplying `settlement_agreement_id`, the `assignment_company_name` of the qualified assignment company assuming the periodic-payment obligation, and the `executed_date` — requires the agreement to be `EXECUTED` (else `ERR_AGREEMENT_INVALID_STATE`) and atomically advances it to `ASSIGNED` with another version increment. The assignment itself begins `EXECUTED`. Assignments may be listed filtered by `settlement_agreement_id` or `status`.

The assignment company then purchases the funding annuity. Recording an `AnnuityPolicy` — with `settlement_agreement_id`, `qualified_assignment_id`, the insurer's `policy_number` and `insurer_name`, the single `premium_cents` paid to the insurer (strictly positive), the policy's pricing `contract_discount_rate_bps` (strictly positive; this is the basis for present-value computations and one side of the commutation rate), the `commutation_rider` (`NONE`, `DEATH_ONLY`, or `DEATH_AND_HARDSHIP`), and optionally `certain_period_end_date` — requires the linked agreement to be `ASSIGNED` (`ERR_AGREEMENT_INVALID_STATE`) and the linked assignment to be `EXECUTED` (`ERR_ASSIGNMENT_INVALID_STATE`). The policy starts `PENDING_ISSUE` with `in_force_date` null. A null `certain_period_end_date` means every payment is life-contingent; otherwise payments due on or before that date survive the payee's death and are paid to the estate or beneficiary (§3.7). Policies may be listed filtered by `settlement_agreement_id`, `qualified_assignment_id`, or `status`.

Marking the policy in force — a case manager supplying `in_force_date` — moves it `PENDING_ISSUE` → `IN_FORCE` (`ERR_POLICY_INVALID_STATE` from any other state), requires the linked agreement still `ASSIGNED` (`ERR_AGREEMENT_INVALID_STATE`), stamps `in_force_date`, bumps the policy's `version`, and cascades the agreement `ASSIGNED` → `FUNDED` with its own version increment. Once a policy linked to an assignment stands `IN_FORCE` or `PARTIALLY_COMMUTED`, a `ComplianceOfficer` may release the obligor's novation, moving the assignment `EXECUTED` → `RELEASED`; releasing without such a policy fails with `ERR_POLICY_INVALID_STATE`, and releasing an assignment no longer `EXECUTED` fails with `ERR_ASSIGNMENT_INVALID_STATE`.

Two system transitions complete the agreement lifecycle. The first payment on the agreement's `ACTIVE` schedule to mature during a clock sweep moves a `FUNDED` agreement to `ACTIVE` (§2.4, step 3). And when the linked policy reaches a terminal state — `EXHAUSTED`, because no payments remain in any non-terminal status, or `FULLY_COMMUTED` after a commutation pay-out — the agreement follows immediately: `ACTIVE` → `CLOSED` after exhaustion, `ACTIVE` → `COMMUTED` after full commutation, each with a version increment. Exhaustion that drains the stream while the agreement is still `FUNDED` closes it the same way: `FUNDED` → `CLOSED`.

### 3.3. Payment Schedules, Escalation, and the Outstanding-Liability Ledger

Payment streams are authored as a `PaymentSchedule` plus its `ScheduledPayment` rows. A `CaseManager` creates a schedule by supplying `settlement_agreement_id`, `effective_from_date` (the first date the schedule governs), and `escalation_anchor_date` (the anniversary anchor for cost-of-living escalation). The agreement must not be `DRAFT`, `CLOSED`, or `COMMUTED` — attempts against those states fail with `ERR_AGREEMENT_INVALID_STATE`. The schedule starts `DRAFT`, and its `supersedes_schedule_id` stays null unless a later activation records which schedule it replaced. Schedules may be listed filtered by `settlement_agreement_id`, `status`, or `supersedes_schedule_id`.

Rows are added one at a time by a case manager: `payment_schedule_id`, which must reference a `DRAFT` schedule (`ERR_SCHEDULE_INVALID_STATE` otherwise); the recipient `payee_id`; `payment_seq_no`, at least 1; `due_date`, not earlier than the schedule's `effective_from_date`; `base_amount_cents`, strictly positive; optional `escalation_rate_bps`, defaulting to zero and never negative; and optional `payment_type`, `PERIODIC` by default or `LUMP_SUM`. Each row is born `SCHEDULED`.

Escalation computes two amounts at creation. The exponent n is the number of anniversaries of the schedule's `escalation_anchor_date` that fall on or before the payment's `due_date` — an anniversary landing exactly on the due date counts, and the anchor date itself is not an anniversary, so the first anniversary falls one year after `escalation_anchor_date`. The payable `amount_cents` compounds with carry-rounding: starting from `base_amount_cents`, each of the n annual steps multiplies the running value by one plus `escalation_rate_bps` divided by ten thousand and rounds half up to a whole cent, and that rounded value carries into the next step; after n steps the running value is `amount_cents`. The `disclosure_amount_cents` compounds unrounded — the base times the annual factor raised to the n-th power — and rounds half up to a whole cent exactly once at the end. The two figures coincide when n is zero or one; with two or more anniversaries, intermediate rounding can shed fractional cents and the figures diverge. `amount_cents` is the only amount ever paid, moved between ledger buckets, or discounted in later workflows; the disclosure figure exists for statements.

Activation is the schedule's pivotal transition and is guarded four ways. Per the global ordering (§2.10), the optimistic-concurrency check fires first — the request must carry `expected_settlement_agreement_version` matching the agreement's current `version`, else `ERR_STALE_AGREEMENT_VERSION`. The schedule must then be `DRAFT` (`ERR_SCHEDULE_INVALID_STATE`), must contain at least one payment row (`ERR_SCHEDULE_HAS_PAYMENTS`), and the agreement must be `FUNDED` or `ACTIVE` (`ERR_AGREEMENT_INVALID_STATE`). On success the schedule moves `DRAFT` → `ACTIVE`; whichever schedule was previously `ACTIVE` for the same agreement, if any, becomes `SUPERSEDED`, and the new schedule's `supersedes_schedule_id` records its id. Supersession cancels the old schedule's pending work: its payments in `SCHEDULED` or `PAYABLE` move to `CANCELLED` with `cancel_reason` = `SUPERSEDED`, while its in-flight payments in `ISSUED`, `RETURNED`, `STALE_DATED`, or `ESCHEATABLE` are untouched. The agreement's `total_scheduled_cents` is recomputed as the sum of `amount_cents` over the new schedule's payments, `outstanding_liability_cents` is recomputed over the new payment set, and the agreement's `version` increments.

The agreement's ledger is the system's fiscal spine. `outstanding_liability_cents` always equals the sum of `amount_cents` over payments of the agreement's `ACTIVE` schedule whose status is `SCHEDULED`, `PAYABLE`, `ISSUED`, `RETURNED`, `STALE_DATED`, or `ESCHEATABLE`; payments in terminal statuses (`CLEARED`, `ESCHEATED`, `TRANSFERRED`, `COMMUTED`, `CANCELLED`) and anything on a superseded or terminated schedule contribute zero. `paid_total_cents` accumulates amounts reaching `CLEARED`. `escheated_total_cents` tracks amounts currently `ESCHEATED` and is decremented on reclaim. `transferred_total_cents` accumulates the nominal amounts of payments sold to factoring companies — a transferred payment leaves the outstanding set because the issuer's obligation to the original payee ends and the factor is paid outside this ledger. `commuted_nominal_total_cents` accumulates the nominal amounts of `COMMUTED` payments, with the discounted lump payout tracked on the commutation request itself. Every payment transition that crosses a set boundary recomputes the affected totals and increments the agreement's `version`; an action that moves several payments across the boundary in one step — schedule activation, transfer effectuation, death-claim settlement, commutation pay-out, or batch finalization — performs a single recomputation and a single version increment per affected agreement.

Two schedule-level endings exist. A schedule whose every remaining non-terminal payment is commuted at pay-out becomes `TERMINATED` (§3.7). And the clock sweep (§2.4, step 2) advances each `SCHEDULED` payment to `PAYABLE` once its `due_date` is on or before the clock date, provided its schedule is `ACTIVE` and its agreement is `FUNDED` or `ACTIVE`; when the agreement was `FUNDED`, that first `PAYABLE` payment also flips the agreement to `ACTIVE`. Because `SCHEDULED` and `PAYABLE` both belong to the outstanding set, maturation recomputes the agreement totals without changing their sum.

### 3.4. Issuing, Clearing, and Recovering Periodic Payments

Issuance is an `OperationsSpecialist` act performed per payment: the payment must be `PAYABLE` (`ERR_PAYMENT_NOT_PAYABLE` otherwise), and the request supplies the `method` — `CHECK` or `EFT`. When the payee is a minor at the current clock date, an `ACTIVE` guardianship case must exist for them or issuance is refused with `ERR_GUARDIANSHIP_REQUIRED`. A successful issue moves `PAYABLE` → `ISSUED`, increments `issue_count` (which starts at zero on a new payment), records `last_issue_method` and the clock date as `last_issued_at` (both null until the first issuance), clears any prior `return_reason` to null, and resolves `payee_name_on_check` — the `guardian_full_name` of the payee's active guardianship when the payee is a minor, otherwise the payee's own `full_name`.

From `ISSUED`, a payment is reconciled one of three ways. Marking cleared — an operations specialist confirming the funds were honored — requires `ISSUED` (`ERR_PAYMENT_NOT_ISSUED`) and moves the payment to `CLEARED`: the agreement's `paid_total_cents` grows by the payment's `amount_cents`, `outstanding_liability_cents` shrinks by the same, the agreement's `version` increments, and the exhaustion check runs — if no non-terminal payments remain, the linked policy becomes `EXHAUSTED` and the agreement follows to `CLOSED`. Reporting a return — supplying a `return_reason` of `BAD_ADDRESS`, `EFT_REJECTED`, or `UNCASHED_STALE` — likewise requires `ISSUED` (`ERR_PAYMENT_NOT_ISSUED`), moves the payment to `RETURNED` with the reason recorded, and automatically opens a `ReturnedPaymentCase`: its `scheduled_payment_id` points at the payment, its `return_reason` is copied from the report, its `opened_by_user_id` captures the reporting `X-User-ID` as the segregation-of-duties anchor, and the case starts `OPEN`. The response returns the updated payment. The third path needs no operator: during a clock sweep, an `ISSUED` payment whose `last_issue_method` is `CHECK` becomes `STALE_DATED` once the clock date is more than 180 days past `last_issued_at` — exactly 180 days leaves it `ISSUED`, and `EFT` issuances never go stale. Staling sets the payment's `return_reason` to `UNCASHED_STALE` but opens no case.

A returned payment is rehabilitated through its case. Authorizing reissue is an operations-specialist action requiring the case `OPEN` (`ERR_CASE_INVALID_STATE`) and the linked payment still `RETURNED` (`ERR_PAYMENT_NOT_RETURNED`); critically, the authorizer's `X-User-ID` must differ from the case's `opened_by_user_id`, or the request fails with `ERR_SOD_VIOLATION`. Success moves the case `OPEN` → `RESOLVED_REISSUE` with `resolution_note` set to `REISSUE_AUTHORIZED` and cascades the payment `RETURNED` → `PAYABLE`, ready to be issued again; both statuses belong to the outstanding set, so `outstanding_liability_cents` does not move. The response returns the updated case. Payments may be listed filtered by `payment_schedule_id`, `payee_id`, `status`, `escheated_in_batch_id`, `transferred_by_petition_id`, or `commuted_by_request_id`; cases may be listed filtered by `scheduled_payment_id` or `status`.

### 3.5. Payee Change Requests

Address, name, and banking changes flow through a `PayeeChangeRequest` so that anything risky gets a second pair of eyes. A payee submits their own request — the `payee_id` must equal their `X-User-ID`, else `ERR_FORBIDDEN_ROLE` — or a `CaseManager` submits on the payee's behalf; in both cases `submitted_by_user_id` captures the submitter's `X-User-ID` as the segregation anchor. The `change_type` selects the payload: `ADDRESS` carries `new_address_line1`, `new_address_city`, `new_address_state_code` (which must resolve to a registered statutory profile), and `new_address_postal_code`; `NAME` carries `new_full_name`; `BANK_ACCOUNT` carries `new_bank_routing_number` and `new_bank_account_number`. The `new_*` fields of the selected type are each optional at submission; omitted fields are stored as null on the request, and an approval that applies a payload writes the stored values onto the payee, null included.

Two paths diverge at submission. An `ADDRESS` request auto-approves — moving straight from `SUBMITTED` to `APPROVED`, overwriting the payee's address fields with the new values and bumping the payee's `version` — but only when no returned-payment case in `OPEN` or `ESCHEAT_PENDING` status exists for any of the payee's scheduled payments; an open investigation routes the request to human review instead, since the address itself is suspect. `NAME` and `BANK_ACCOUNT` requests always land `UNDER_REVIEW`. A `ComplianceOfficer` then approves or rejects: both actions require the request `UNDER_REVIEW` (`ERR_CHANGE_REQUEST_INVALID_STATE`), and approval additionally enforces segregation of duties — the approver's `X-User-ID` must differ from `submitted_by_user_id` (`ERR_SOD_VIOLATION`). Approval applies the payload: new address fields for `ADDRESS`, `full_name` for `NAME`, while `BANK_ACCOUNT` details are recorded on the request only; in every case the payee's `version` increments. Rejection simply terminates the request as `REJECTED`. Because the payee's `address_state_code` selects the statutory profile, an approved move to a different state means all subsequent minority and dormancy evaluations use the new state's profile. One system event intervenes from outside: settlement of a death claim for the payee auto-rejects any of that payee's requests still `UNDER_REVIEW` (§3.7). Requests may be listed filtered by `payee_id` or `status`.

### 3.6. Secondary-Market Transfer Petitions

A payee may sell some or all remaining payments to a factoring company, but only under court supervision, as state Structured Settlement Protection Acts demand. Drafting a `TransferPetition` — by the payee personally, with `payee_id` equal to `X-User-ID` (`ERR_FORBIDDEN_ROLE` otherwise), or by a `CaseManager` on the payee's behalf — takes `settlement_agreement_id` (the agreement must be `FUNDED` or `ACTIVE`, else `ERR_AGREEMENT_INVALID_STATE`), `payee_id` (which must resolve to a registered payee but need not be the agreement's primary payee), `factoring_company_name`, the offered `purchase_price_cents` (strictly positive), and a due-date window from `transfer_start_date` through `transfer_end_date`, both dates inclusive, with the end not earlier than the start. The creation clock date is the valuation date for every figure computed below.

Creation freezes the economics. The matched set comprises payments of the agreement's `ACTIVE` schedule in `SCHEDULED` or `PAYABLE` status whose `due_date` falls inside the window; an empty set fails creation with `ERR_NO_TRANSFERRABLE_PAYMENTS`, and `transferred_payment_count` records the matched count. Each matched payment's time factor is the number of days from the valuation date to its `due_date`, divided by 365. `present_value_cents` discounts each matched payment at the linked policy's `contract_discount_rate_bps`: every payment's `amount_cents` divided by one plus the contract rate raised to that payment's time factor, each result rounded half up to whole cents first and only then summed — the pinned rounding order is the contract, since summing unrounded values and rounding once can differ by a cent or more. Two rates derive from the same set. The `disclosed_discount_rate_bps`, the aggregate consumer-disclosure figure, is the nominal total of the matched set minus `purchase_price_cents`, divided by the nominal total, divided by the weighted-average life — the sum over the set of each payment's `amount_cents` multiplied by its time factor, divided by the nominal total — then multiplied by ten thousand and rounded half up to a whole basis point — or recorded as 0 when the weighted-average life is zero (every matched payment due on the valuation date). The `effective_annual_rate_bps`, the statutory figure, is ten thousand times the rate at which the matched payments' discounted `amount_cents` exactly equal `purchase_price_cents` — solved by bisection, and negative when the price exceeds the undiscounted nominal total — rounded half up; on any discounted multi-payment set it is strictly greater than the aggregate figure, and the SSPA cap applies to this actuarial value alone.

Filing is where the statute bites. The petition must be `DRAFT` (`ERR_PETITION_INVALID_STATE`), and a payee filing for themselves must be the petition's payee (`ERR_FORBIDDEN_ROLE`). The business guards then apply in the global order of §2.10: if the payee is a minor at filing, an `ACTIVE` guardianship case must exist (`ERR_GUARDIANSHIP_REQUIRED`); the petition's `effective_annual_rate_bps` must not exceed the governing profile's `sspa_max_discount_rate_bps` (`ERR_EFFECTIVE_RATE_EXCEEDS_CAP`, HTTP 422); no earlier `COURT_DENIED` petition for the same payee with `prejudice` = `WITH` may have a `court_order_date` within the prior 365 days — while the clock date remains earlier than one year after that order, refiling is barred (`ERR_REFILE_BARRED_WITH_PREJUDICE`); the matched payment set must be disjoint from the matched sets of every other petition on the same agreement in `FILED`, `DISCLOSURE_SERVED`, `HEARING_SCHEDULED`, `COURT_APPROVED`, or `EFFECTIVE` (`ERR_TRANSFER_WINDOW_OVERLAP`) — for an `EFFECTIVE` petition, whose payments have left the matchable statuses, the set is the payments carrying its `transferred_by_petition_id`; and `purchase_price_cents` must not exceed `present_value_cents` (`ERR_PRICE_EXCEEDS_PRESENT_VALUE`, HTTP 422). Filing stamps `filed_at` with the clock date, `filed_by_user_id` with the caller, and — decisively for everything downstream — captures `state_code` from the payee's `address_state_code`, fixing the SSPA forum state and its governing profile even if the payee later moves. The petition is now `FILED`.

A `CaseManager` records statutory disclosure service, moving `FILED` → `DISCLOSURE_SERVED` and stamping `disclosure_served_at` with the clock date. Scheduling the hearing — supplying `hearing_date` and optionally `ipa_completed_at` — requires `DISCLOSURE_SERVED` (`ERR_PETITION_INVALID_STATE`) and clears two temporal gates in order: the clock date must be on or after `disclosure_served_at` plus the governing profile's `disclosure_cooling_off_days` (`ERR_COOLING_OFF_NOT_ELAPSED`), and when the profile's `ipa_required` is set, `ipa_completed_at` must be supplied (`ERR_IPA_REQUIRED`). Success stores `hearing_date` and, when provided, `ipa_completed_at`, moving the petition to `HEARING_SCHEDULED`.

The judicial outcome is recorded by a `JudicialRecorder` — never by the petitioner: the recorder's `X-User-ID` must differ from the petition's `filed_by_user_id` (`ERR_SOD_VIOLATION`), and the petition must be `HEARING_SCHEDULED` (`ERR_PETITION_INVALID_STATE`). The `outcome` drives two sibling branches with symmetric bookkeeping. An `outcome` of `APPROVED` or `APPROVED_MODIFIED` moves the petition to `COURT_APPROVED`: `court_outcome`, `court_order_date`, and `prejudice` are stamped from the inputs, `order_recorded_by_user_id` captures the recorder, and `approved_price_cents` is set — for `APPROVED_MODIFIED` from the input, which must be present and strictly below `purchase_price_cents` (else `ERR_INVALID_REQUEST`), and otherwise mirrored from `purchase_price_cents`. An `outcome` of `DENIED` moves the petition to `COURT_DENIED`: `prejudice` — `WITH` or `WITHOUT` — must be present (else `ERR_INVALID_REQUEST`) and is stamped alongside the other order fields; a denial with prejudice is what feeds the 365-day refile bar above.

An approved transfer is consummated when a `ComplianceOfficer` effectuates the petition, moving it `COURT_APPROVED` → `EFFECTIVE`. Every payment of the agreement's `ACTIVE` schedule in `SCHEDULED` or `PAYABLE` whose `due_date` still falls inside the window moves to `TRANSFERRED` with `transferred_by_petition_id` recording the petition; if re-matching at effectuation finds the set empty — payments may have been cancelled or commuted since creation — the effectuation fails with `ERR_NO_TRANSFERRABLE_PAYMENTS`. Each transferred payment shrinks the agreement's `outstanding_liability_cents` by its `amount_cents` and grows `transferred_total_cents` by the same, with the single recomputation and version increment of §3.3; the exhaustion cascade then runs, so a transfer covering every remaining payment leaves the policy `EXHAUSTED` and the agreement `CLOSED`. Court orders go stale: the clock sweep moves a `COURT_APPROVED` petition to `EXPIRED` once the clock date is more than 60 days past its `court_order_date` without effectuation. Either the payee (self only, `ERR_FORBIDDEN_ROLE`) or a `CaseManager` may withdraw a petition — from `FILED`, from `DISCLOSURE_SERVED`, or from `HEARING_SCHEDULED` alike, each moving it to `WITHDRAWN`, while a withdrawal attempt from any other state fails with `ERR_PETITION_INVALID_STATE`. Settlement of the payee's death claim auto-withdraws petitions in those same three states (§3.7). Petitions may be listed filtered by `settlement_agreement_id`, `payee_id`, or `status`.

### 3.7. Death Claims and Commutation

Death and hardship unlock two intertwined workflows. A `CaseManager` reports a `DeathClaim` with `payee_id` — the payee must be `ACTIVE`, else `ERR_CLAIM_INVALID_STATE` — plus `settlement_agreement_id`, `date_of_death`, the `claimant_type` (`BENEFICIARY` or `ESTATE`, determining who receives certain-period and death-benefit payments), and `claimant_name`. The claim starts `REPORTED` with `denial_reason` null. Claims may be listed filtered by `payee_id`, `settlement_agreement_id`, or `status`.

Settlement, performed by a `ComplianceOfficer` on a `REPORTED` claim (`ERR_CLAIM_INVALID_STATE` otherwise), detonates the widest cascade in the system. The payee moves `ACTIVE` → `DECEASED`, with `deceased_date` set to the claim's `date_of_death` and a version bump. The payee's `ACTIVE` guardianship case, if any, is `TERMINATED` with `terminated_at_date` set to the date of death. The payee's change requests still `UNDER_REVIEW` are auto-`REJECTED`, and the payee's transfer petitions in `FILED`, `DISCLOSURE_SERVED`, or `HEARING_SCHEDULED` are auto-`WITHDRAWN`. Mortality then meets the certain period: among the agreement's payments for this payee in `SCHEDULED` or `PAYABLE`, those with `due_date` strictly after the policy's `certain_period_end_date` are cancelled with `cancel_reason` = `DEATH` — and when `certain_period_end_date` is null, every payment is life-contingent, so all of them are cancelled — while payments due on or before the certain-period end survive for the estate or beneficiary. Each cancellation out of `PAYABLE` reduces `outstanding_liability_cents`, and the agreement totals are then recomputed once. The exhaustion cascade follows: if no non-terminal payments remain, the policy becomes `EXHAUSTED` and the agreement follows `ACTIVE` → `CLOSED`. Denial is the quiet sibling branch: a `ComplianceOfficer` moves `REPORTED` → `DENIED`, supplying a `denial_reason`. Denial is not final — a `CaseManager` may resubmit the claim with a new evidence package, moving `DENIED` → `REPORTED` (`ERR_CLAIM_INVALID_STATE` from any other state) and clearing `denial_reason` to null.

Commutation converts future payments into a discounted lump sum where contract and statute allow. A `CaseManager` creates a `CommutationRequest` naming `annuity_policy_id`, `settlement_agreement_id`, and the `reason` — `DEATH` or `HARDSHIP` — and carrying the optimistic-concurrency field `expected_annuity_policy_version` (§2.7; a stale policy version fails with `ERR_STALE_POLICY_VERSION`). When the reason is `DEATH`, `death_claim_id` must be supplied — a missing one fails shape validation with `ERR_INVALID_REQUEST` — and must reference a `SETTLED` claim for the same agreement (`ERR_CLAIM_INVALID_STATE` otherwise); a `death_claim_id` supplied with `HARDSHIP` must still resolve to an existing claim but is recorded as null. Legality is gated before any economics: the policy's `commutation_rider` must allow the requested reason — `DEATH` requires `DEATH_ONLY` or `DEATH_AND_HARDSHIP`, `HARDSHIP` requires `DEATH_AND_HARDSHIP`, and `NONE` allows nothing — and the primary payee's residence profile's `commutation_permitted` must be true; either failure is `ERR_COMMUTATION_NOT_PERMITTED` (HTTP 403).

The eligible set is computed at creation: payments of the agreement's `ACTIVE` schedule in `SCHEDULED` or `PAYABLE` status with `due_date` strictly after the creation clock date. An empty set fails creation with `ERR_NO_COMMUTABLE_PAYMENTS`; otherwise `covered_payment_count` records its size. The discount rate is the lesser of the policy's `contract_discount_rate_bps` and the primary payee's residence profile's `sspa_max_discount_rate_bps`. Each eligible payment's `amount_cents` is discounted over its own time factor — days from the creation clock date to `due_date`, divided by 365 — rounded half up to whole cents per payment, and the rounded amounts are summed into the present-value total, the same pinned per-payment-then-sum order as the transfer present value. The `fee_cents` is, for `HARDSHIP`, three percent of that present-value total rounded half up, capped at 250 dollars (25,000 cents); for `DEATH` it is zero. The `commuted_value_cents` is the present-value total minus the fee. Creation itself advances the policy's `version` — the anchor that makes the optimistic-concurrency check on a subsequent request meaningful — and the request starts `REQUESTED`.

A `ComplianceOfficer` approves or denies a `REQUESTED` commutation (`ERR_COMMUTATION_INVALID_STATE` from any other state), moving it to `APPROVED` or `DENIED`. Pay-out is the `OperationsSpecialist` step and requires `APPROVED` (`ERR_COMMUTATION_INVALID_STATE`): the request becomes `PAID_OUT`, and every covered payment — the eligible set frozen at creation — moves from `SCHEDULED` or `PAYABLE` to `COMMUTED` with `commuted_by_request_id` recording the request, each payment shrinking the agreement's `outstanding_liability_cents` and growing `commuted_nominal_total_cents` by its `amount_cents`. The policy then follows the remainder: when non-terminal payments survive it moves — or stays — `PARTIALLY_COMMUTED`; when none survive it becomes `FULLY_COMMUTED`, the exhaustion-style close does not apply, and the agreement cascades `ACTIVE` → `COMMUTED`. A schedule left with no non-terminal payments becomes `TERMINATED`. Either way the policy's `version` increments at pay-out. Commutation requests may be listed filtered by `annuity_policy_id`, `settlement_agreement_id`, `death_claim_id`, or `status`.

### 3.8. Dormancy, Escheatment, and Reclaim

Unclaimed property is the system's final accounting frontier. Dormancy is evaluated against the payee-residence profile: a payment in `ISSUED`, `STALE_DATED`, or `RETURNED` becomes `ESCHEATABLE` when the clock date is strictly later than the payment's `due_date` plus the profile's `dormancy_years` — on the dormancy anniversary itself the payment is not yet escheatable; it becomes so the day after. The clock sweep applies this rule automatically (§2.4, step 5), and because the stale-check step runs earlier in the same pass, a check payment can travel `ISSUED` → `STALE_DATED` → `ESCHEATABLE` within a single clock-set. The sweep never touches the payment's returned-payment case — the case stays `OPEN`.

A `ComplianceOfficer` may also force the issue manually through the returned-payment case: escalation requires the case `OPEN` (`ERR_CASE_INVALID_STATE`) and the same dormancy condition already satisfied, else `ERR_DORMANCY_NOT_MET`. Manual escalation moves the case `OPEN` → `ESCHEAT_PENDING` and the linked payment to `ESCHEATABLE`. The response returns the updated case.

Escheatment itself is batched per state. A `ComplianceOfficer` opens an `EscheatmentBatch` with a `state_code` and a `batch_period` label in YYYY-MM form; at most one `OPEN` batch may exist per state, and a second attempt fails with `ERR_OPEN_BATCH_EXISTS`. The batch records `opened_by_user_id` — the segregation anchor — and starts with `swept_count`, `swept_amount_cents`, `reclaimed_count`, and `reclaimed_amount_cents` all at zero. Finalizing is likewise a compliance-officer act but must not be performed by the opener (`ERR_SOD_VIOLATION`) and requires the batch `OPEN` (`ERR_BATCH_INVALID_STATE`). Finalization sweeps every `ESCHEATABLE` payment whose payee's `address_state_code` equals the batch's `state_code` into `ESCHEATED`, stamping `escheated_in_batch_id` with the batch's id; `swept_count` and `swept_amount_cents` record the count and the summed `amount_cents` of the sweep — finalizing an empty batch is allowed and records zeros. Each swept payment moves its `amount_cents` from the agreement's `outstanding_liability_cents` to its `escheated_total_cents`, closes the payment's `OPEN` or `ESCHEAT_PENDING` returned-payment case as `CLOSED_ESCHEATED` with `resolution_note` set to `ESCHEATED`, and — after the single per-agreement recomputation and version increment of §3.3 — runs the exhaustion cascade — a sweep that drains the last non-terminal payments takes the policy to `EXHAUSTED` and the agreement to `CLOSED`. The batch ends `FINALIZED`.

Escheatment is reversible when an owner surfaces. Reclaiming is an `OperationsSpecialist` action requiring the payment `ESCHEATED` (`ERR_PAYMENT_NOT_ESCHEATED`), an `OPEN` escheatment batch for the payee's `address_state_code` (`ERR_NO_OPEN_ESCHEAT_BATCH`), and the linked agreement neither `CLOSED` nor `COMMUTED` (`ERR_AGREEMENT_INVALID_STATE`). Success returns the payment to `PAYABLE`: the agreement's `escheated_total_cents` shrinks and its `outstanding_liability_cents` grows by the payment's `amount_cents` with a version bump, the payment's `escheated_in_batch_id` and `return_reason` clear to null, and the open batch for that state is credited — its `reclaimed_count` grows by one and its `reclaimed_amount_cents` by the payment's amount, tallies that accrue only while the batch is `OPEN` and independently of its sweep totals. Batches may be listed filtered by `state_code` or `status`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — every state transition, action, and the clock-setting capability — return `200 OK`. Within paths, resource identifiers appear as braced camel-case variables — `profileId`, `payeeId`, `caseId`, `agreementId`, `assignmentId`, `policyId`, `scheduleId`, `paymentId`, `requestId`, `petitionId`, `claimId`, `commutationId`, and `batchId` — each denoting the `id` of the corresponding resource; note that `caseId` identifies a guardianship case in the guardianship paths and a returned-payment case in the returned-payment paths. The table below is a navigation aid: request payloads, response bodies, side effects, and validation semantics are specified by the narratives of §2 and §3, not by this table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/annuity/_clock/set_current_utc` | Advance the logical clock and run the system sweep | PlatformAdmin |
| POST | `/annuity/state-statute-profiles` | Create a per-state statutory profile | PlatformAdmin |
| GET | `/annuity/state-statute-profiles` | List statute profiles | Any |
| GET | `/annuity/state-statute-profiles/{profileId}` | Get one statute profile | Any |
| POST | `/annuity/payees` | Register a payee | CaseManager |
| GET | `/annuity/payees` | List payees | Any |
| GET | `/annuity/payees/{payeeId}` | Get one payee | Any |
| POST | `/annuity/guardianship-cases` | Open a guardianship case for a payee | CaseManager |
| GET | `/annuity/guardianship-cases` | List guardianship cases | Any |
| GET | `/annuity/guardianship-cases/{caseId}` | Get one guardianship case | Any |
| POST | `/annuity/guardianship-cases/{caseId}/activate` | Activate a pending guardianship case | ComplianceOfficer |
| POST | `/annuity/guardianship-cases/{caseId}/revoke` | Revoke an active guardianship | ComplianceOfficer |
| POST | `/annuity/settlement-agreements` | Create a settlement agreement | CaseManager |
| GET | `/annuity/settlement-agreements` | List settlement agreements | Any |
| GET | `/annuity/settlement-agreements/{agreementId}` | Get one agreement with ledger totals | Any |
| POST | `/annuity/settlement-agreements/{agreementId}/execute` | Execute a DRAFT agreement | CaseManager |
| POST | `/annuity/qualified-assignments` | Create and execute a qualified assignment | CaseManager |
| GET | `/annuity/qualified-assignments` | List qualified assignments | Any |
| GET | `/annuity/qualified-assignments/{assignmentId}` | Get one qualified assignment | Any |
| POST | `/annuity/qualified-assignments/{assignmentId}/release` | Release the obligor once the annuity is in force | ComplianceOfficer |
| POST | `/annuity/annuity-policies` | Record the annuity purchase by the assignment company | CaseManager |
| GET | `/annuity/annuity-policies` | List annuity policies | Any |
| GET | `/annuity/annuity-policies/{policyId}` | Get one annuity policy | Any |
| POST | `/annuity/annuity-policies/{policyId}/mark-in-force` | Mark a policy in force | CaseManager |
| POST | `/annuity/payment-schedules` | Create a DRAFT payment schedule | CaseManager |
| GET | `/annuity/payment-schedules` | List payment schedules | Any |
| GET | `/annuity/payment-schedules/{scheduleId}` | Get one payment schedule | Any |
| POST | `/annuity/payment-schedules/{scheduleId}/activate` | Activate a DRAFT schedule, superseding the current one | CaseManager |
| POST | `/annuity/scheduled-payments` | Add a payment row to a DRAFT schedule | CaseManager |
| GET | `/annuity/scheduled-payments` | List payments | Any |
| GET | `/annuity/scheduled-payments/{paymentId}` | Get one payment | Any |
| POST | `/annuity/scheduled-payments/{paymentId}/issue` | Issue a PAYABLE payment by check or EFT | OperationsSpecialist |
| POST | `/annuity/scheduled-payments/{paymentId}/mark-cleared` | Mark an ISSUED payment cleared | OperationsSpecialist |
| POST | `/annuity/scheduled-payments/{paymentId}/report-returned` | Report an ISSUED payment returned | OperationsSpecialist |
| POST | `/annuity/scheduled-payments/{paymentId}/reclaim-escheat` | Reclaim an ESCHEATED payment | OperationsSpecialist |
| GET | `/annuity/returned-payment-cases` | List returned-payment cases | Any |
| GET | `/annuity/returned-payment-cases/{caseId}` | Get one returned-payment case | Any |
| POST | `/annuity/returned-payment-cases/{caseId}/authorize-reissue` | Authorize reissue of the returned payment | OperationsSpecialist |
| POST | `/annuity/returned-payment-cases/{caseId}/escalate-escheat` | Escalate an OPEN case toward escheatment | ComplianceOfficer |
| POST | `/annuity/payee-change-requests` | Submit a payee change request | Payee, CaseManager |
| GET | `/annuity/payee-change-requests` | List change requests | Any |
| GET | `/annuity/payee-change-requests/{requestId}` | Get one change request | Any |
| POST | `/annuity/payee-change-requests/{requestId}/approve` | Approve an UNDER_REVIEW change request | ComplianceOfficer |
| POST | `/annuity/payee-change-requests/{requestId}/reject` | Reject an UNDER_REVIEW change request | ComplianceOfficer |
| POST | `/annuity/transfer-petitions` | Draft a secondary-market transfer petition | Payee, CaseManager |
| GET | `/annuity/transfer-petitions` | List transfer petitions | Any |
| GET | `/annuity/transfer-petitions/{petitionId}` | Get one transfer petition | Any |
| POST | `/annuity/transfer-petitions/{petitionId}/file` | File the petition | Payee, CaseManager |
| POST | `/annuity/transfer-petitions/{petitionId}/serve-disclosure` | Record statutory disclosure service | CaseManager |
| POST | `/annuity/transfer-petitions/{petitionId}/schedule-hearing` | Schedule the court hearing | CaseManager |
| POST | `/annuity/transfer-petitions/{petitionId}/withdraw` | Withdraw a petition before adjudication | Payee, CaseManager |
| POST | `/annuity/transfer-petitions/{petitionId}/record-court-order` | Record the judicial outcome | JudicialRecorder |
| POST | `/annuity/transfer-petitions/{petitionId}/effectuate` | Effectuate a court-approved transfer | ComplianceOfficer |
| POST | `/annuity/death-claims` | Report a payee death | CaseManager |
| GET | `/annuity/death-claims` | List death claims | Any |
| GET | `/annuity/death-claims/{claimId}` | Get one death claim | Any |
| POST | `/annuity/death-claims/{claimId}/settle` | Settle a death claim | ComplianceOfficer |
| POST | `/annuity/death-claims/{claimId}/deny` | Deny a death claim | ComplianceOfficer |
| POST | `/annuity/death-claims/{claimId}/resubmit` | Resubmit a denied claim with new evidence | CaseManager |
| POST | `/annuity/commutation-requests` | Request commutation of remaining payments | CaseManager |
| GET | `/annuity/commutation-requests` | List commutation requests | Any |
| GET | `/annuity/commutation-requests/{commutationId}` | Get one commutation request | Any |
| POST | `/annuity/commutation-requests/{commutationId}/approve` | Approve a commutation request | ComplianceOfficer |
| POST | `/annuity/commutation-requests/{commutationId}/deny` | Deny a commutation request | ComplianceOfficer |
| POST | `/annuity/commutation-requests/{commutationId}/pay-out` | Pay out an approved commutation | OperationsSpecialist |
| POST | `/annuity/escheatment-batches` | Open an escheatment batch for a state | ComplianceOfficer |
| GET | `/annuity/escheatment-batches` | List escheatment batches | Any |
| GET | `/annuity/escheatment-batches/{batchId}` | Get one escheatment batch | Any |
| POST | `/annuity/escheatment-batches/{batchId}/finalize` | Finalize a batch, sweeping ESCHEATABLE payments | ComplianceOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this table is the canonical index of identifiers and statuses.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STATE_PROFILE_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_AGREEMENT_VERSION` | 412 Precondition Failed |
| `ERR_STALE_POLICY_VERSION` | 412 Precondition Failed |
| `ERR_AGREEMENT_INVALID_STATE` | 409 Conflict |
| `ERR_ASSIGNMENT_INVALID_STATE` | 409 Conflict |
| `ERR_POLICY_INVALID_STATE` | 409 Conflict |
| `ERR_SCHEDULE_INVALID_STATE` | 409 Conflict |
| `ERR_SCHEDULE_HAS_PAYMENTS` | 409 Conflict |
| `ERR_PAYMENT_NOT_PAYABLE` | 409 Conflict |
| `ERR_PAYMENT_NOT_ISSUED` | 409 Conflict |
| `ERR_PAYMENT_NOT_RETURNED` | 409 Conflict |
| `ERR_PAYMENT_NOT_ESCHEATED` | 409 Conflict |
| `ERR_CASE_INVALID_STATE` | 409 Conflict |
| `ERR_CHANGE_REQUEST_INVALID_STATE` | 409 Conflict |
| `ERR_PETITION_INVALID_STATE` | 409 Conflict |
| `ERR_CLAIM_INVALID_STATE` | 409 Conflict |
| `ERR_COMMUTATION_INVALID_STATE` | 409 Conflict |
| `ERR_BATCH_INVALID_STATE` | 409 Conflict |
| `ERR_GUARDIANSHIP_INVALID_STATE` | 409 Conflict |
| `ERR_GUARDIANSHIP_REQUIRED` | 403 Forbidden |
| `ERR_GUARDIANSHIP_OVERLAP` | 409 Conflict |
| `ERR_SOD_VIOLATION` | 403 Forbidden |
| `ERR_EFFECTIVE_RATE_EXCEEDS_CAP` | 422 Unprocessable Entity |
| `ERR_PRICE_EXCEEDS_PRESENT_VALUE` | 422 Unprocessable Entity |
| `ERR_REFILE_BARRED_WITH_PREJUDICE` | 409 Conflict |
| `ERR_TRANSFER_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_NO_TRANSFERRABLE_PAYMENTS` | 409 Conflict |
| `ERR_IPA_REQUIRED` | 409 Conflict |
| `ERR_COOLING_OFF_NOT_ELAPSED` | 409 Conflict |
| `ERR_COMMUTATION_NOT_PERMITTED` | 403 Forbidden |
| `ERR_NO_COMMUTABLE_PAYMENTS` | 409 Conflict |
| `ERR_DORMANCY_NOT_MET` | 409 Conflict |
| `ERR_OPEN_BATCH_EXISTS` | 409 Conflict |
| `ERR_NO_OPEN_ESCHEAT_BATCH` | 409 Conflict |
| `ERR_DUPLICATE_CASE_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_STATE_PROFILE` | 409 Conflict |
