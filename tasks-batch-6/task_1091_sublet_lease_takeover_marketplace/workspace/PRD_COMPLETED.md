# Sublet & Lease-Takeover Marketplace API — Product Requirements Document

## 1. Introduction

The Sublet & Lease-Takeover Marketplace connects three parties who rarely trust one another by default: a property owner who holds the master lease, an original tenant who needs to leave a unit before their term ends, and a prospective occupant who wants to move in. Bringing these parties to a fully-signed, deposit-funded agreement requires the platform to act as an impartial coordinator — verifying that a lease genuinely permits subletting or assignment, screening applicants against an income policy the landlord can tighten, capping and escrowing deposits, prorating the first period of rent, sequencing three e-signatures, and scheduling a physical key handoff on the landlord's calendar without double-booking.

This document specifies the REST API that governs that entire journey. The system models a multi-party negotiation whose success depends on every participant's state advancing in lockstep: a listing cannot open until its lease is verified, an application cannot match until it passes screening, an agreement cannot execute until all three required signatures are collected, and a deposit cannot be released until the keys have changed hands. Because several of these steps carry money (deposits held in escrow, prorated rent, platform fees) and scarce resources (occupancy slots on a single unit, time slots on a landlord's calendar), the platform enforces conservation invariants and optimistic-concurrency protections that keep the ledger and the occupancy count honest even as listings are withdrawn, agreements are superseded, and disputes are resolved. The requirements below define the data model, the lifecycle of each resource, the calculations, and the exhaustive set of validation and error semantics an implementation must honour.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated by two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). This applies to every endpoint; there is no anonymous access, and even the logical-clock control endpoint requires valid headers.

The system recognises exactly five roles, spelled precisely as follows: `Landlord`, `Leaseholder`, `Applicant`, `ComplianceOfficer`, and `PlatformAdmin`. When a request carries a role that exists but is not permitted to perform the requested operation, the platform responds with `ERR_UNAUTHORIZED` (HTTP 403).

Three of these roles are **entity-backed**, meaning the `X-User-ID` header ties the caller to a persisted record and drives ownership checks:

- When `X-User-Role` is `Landlord`, `X-User-ID` is the `id` of the acting `Landlord`. Ownership checks on any resource that references a landlord compare that resource's owning landlord foreign key to `X-User-ID` — for example, a lease is owned by the landlord in its `landlord_id`, and a handoff appointment sits on the calendar identified by its `landlord_id`.
- When `X-User-Role` is `Leaseholder`, `X-User-ID` is the `id` of the acting `Leaseholder`. Ownership checks compare a resource's owning leaseholder foreign key to `X-User-ID`; a lease is owned by the leaseholder in its `leaseholder_id`, and a listing (and every agreement, settlement, and dispute downstream of it) inherits its ownership from that lease's `leaseholder_id`.
- When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant`. Ownership checks compare a resource's owning applicant foreign key to `X-User-ID`; an application is owned by the applicant in its `applicant_id`.

When an entity-backed actor targets a resource they do not own, the request is rejected with `ERR_OWNERSHIP_VIOLATION` (HTTP 403). The leaseholder-inheritance rule above governs leaseholder-initiated actions; when a `Landlord` or `Applicant` instead acts in their own capacity on a resource downstream of a lease — a `Landlord` or `Applicant` e-signing an agreement, an `Applicant` funding a settlement, or an `Applicant` filing a dispute — the ownership check compares that actor's own foreign key (the agreement's lease `landlord_id`, or the agreement's application `applicant_id`) to `X-User-ID` rather than the `leaseholder_id`.

The remaining two roles are **opaque operators**. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the platform may record it (for instance, no entity FK compares against it) but never treats it as a resource owner. Likewise, when `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier used to onboard parties, manage fees, and drive the logical clock, and is never compared to any entity's `id`. One entity-backed field does capture an actor identity directly: when a party e-signs, the platform stamps the `signer_id` of the created signature with the caller's `X-User-ID`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Values outside these bounds are treated as a malformed request (`ERR_VALIDATION`, HTTP 400).

Unless a specific endpoint states otherwise, all list endpoints return resources sorted by their `created_at` timestamp in ascending order; resources sharing an identical `created_at` (common under the logical clock, which does not advance on its own) are further ordered by their creation sequence, i.e. insertion order. Every list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Most resources in the system carry a standard set of system-managed fields:

- `id` — a unique, server-minted UUID with no type prefix. It is identity only; clients never supply it.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits, fixed at the moment of creation.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer that starts at 1 on creation and increments by 1 on every mutation. It underpins the optimistic-concurrency mechanism of §2.6.

`Landlord`, `Leaseholder`, `Applicant`, `Lease`, `Listing`, `Application`, `ScreeningReport`, `Agreement`, `Settlement`, `HandoffAppointment`, `Dispute`, and `Fee` all carry the full set above. The one exception is `Signature`: a signature is immutable once written, so it carries only `id` and `created_at` — it has neither an `updated_at` nor a `version` field.

All timestamps and all date comparisons in the system are taken from the logical clock described in §2.5, never from wall-clock time.

### 2.5. The Logical Clock

The platform runs on a logical clock rather than the host's wall clock. On server startup the clock reads `2026-05-01T00:00:00Z`, and it never falls back to real time. An operator capability lets a `PlatformAdmin` or `ComplianceOfficer` set the clock to a supplied instant, provided as the `to_iso8601` field; every timestamp minted afterward (including `created_at`, `updated_at`, and a signature's `signed_at`) and every date or datetime comparison (availability windows, occupancy overlaps, appointment buffers) is evaluated against the clock's current value. This makes date-sensitive behaviour fully deterministic and test-drivable.

### 2.6. Optimistic Concurrency Control and Listing Supersession

Drafting an agreement is the one write in the system guarded by optimistic concurrency, because a single OPEN listing may attract competing drafts. When a leaseholder drafts an agreement, the request must carry `expected_listing_version`, holding the `version` of the target `Listing` that the client last observed. If that value does not match the listing's current `version`, the create is rejected with `ERR_STALE_LISTING_VERSION` (HTTP 412), and no agreement is drafted.

The reason a stale version can arise is supersession: a successful agreement draft against an OPEN listing legitimately voids any prior non-terminal agreement on that same listing and increments the listing's `version` by 1. A client that read the listing before an earlier draft superseded the field, and then attempts its own draft carrying the pre-supersede version, is therefore working from an outdated view of the listing's terms and match state, and its request must fail rather than overwrite a draft it never observed. No other endpoint takes a version field; supersession and its version bump are internal to the agreement-draft flow.

### 2.7. Monetary Values, Rates, and Rounding

All monetary amounts are integer cents. Wherever a calculation would produce a fractional cent, the platform rounds half up (a value exactly at the midpoint rounds away from zero to the next whole cent) to land on an integer number of cents. The affordability ratio and income multiple of a screening report are the only non-cent numeric outputs; each is a `number` rounded half up to four decimal places for storage, while the qualifying comparison that consumes it is evaluated at full precision before that rounding (see §3.3).

The platform fee is computed component-by-component with rounding applied **before** summation, never after: the service component and the processing component are each rounded half up to whole cents independently, and only then added together. Rounding the sum instead of the parts can differ by one cent, so the order is contractual, not incidental.

### 2.8. Escrow and Occupancy Conservation

Two quantities in the system are conserved and must reconcile at all times.

The first is the **platform escrow balance**. The total money held in escrow always equals the sum of `deposit_held_cents` across every settlement. A settlement's `deposit_held_cents` equals its `deposit_amount_cents` while the settlement is FUNDED or HANDED_OFF, and is exactly 0 in every terminal state (RELEASED, REFUNDED, FORFEITED) and while PENDING. Consequently, funding a settlement adds its deposit to escrow, and each compensating exit — release back to the landlord/leaseholder, refund to the applicant, or forfeiture to the leaseholder — removes exactly the same amount, so a fund paired with its eventual settlement leaves the escrow balance where it started.

The second is the **occupancy-slot count** on a lease. A lease's `active_occupancy_count` always equals the number of agreements on that lease whose status is EXECUTED or ACTIVE. Reserving occupancy (an agreement reaching EXECUTED) increments the count by 1, and each compensating release (that agreement reaching COMPLETED, VOID, or TERMINATED) decrements it by 1, so the count never drifts. This count is the quantity the unit-occupancy overlap check in §3.4 protects.

### 2.9. Validation Ordering and Resource Resolution

When several checks could reject the same request, the platform evaluates them in a fixed precedence so that the returned `error_id` is deterministic:

1. **Authentication** first — headers present and well-formed, else `ERR_UNAUTHENTICATED` (401).
2. **Authorization** next — the role is permitted for the operation, else `ERR_UNAUTHORIZED` (403).
3. **Ownership** — for an entity-backed actor operating on a resource it must own, `X-User-ID` must equal the resource's owning foreign key (such as `leaseholder_id`, `landlord_id`, or `applicant_id`), else `ERR_OWNERSHIP_VIOLATION` (403).
4. **Existence** — every id in the path or body must resolve to an existing resource, checked left-to-right; the first unresolved id yields its specific not-found error (404). A request naming a missing listing under a nested read fails on the listing before the platform looks at anything further down the path.
5. **Source state** — the target resource must be in a legal state for the requested transition, else the transition's specific conflict error (409).
6. **Cross-entity referential preconditions** — such as a lease being VERIFIED, a settlement being FUNDED, or the absence of a duplicate application (409).
7. **Screening gate** — screening must have passed where required (409).
8. **Business constraints** — listing type permitted by lease flags, term length, signer-role legality (409).
9. **Temporal rules** — availability window (422), occupancy overlap (409), and appointment buffer (409).
10. **Fiscal** — funded amount matching the required total (402).
11. **Optimistic concurrency** — the listing version match on agreement draft (412).

Malformed bodies, missing required fields, and type or range violations surface as `ERR_VALIDATION` (HTTP 400) and are caught alongside the structural checks above.

### 2.10. Cascades and Consistency

Several operations mutate more than one resource in a single logical step. Whenever the platform performs such a cascade, every affected resource independently has its `updated_at` refreshed and its `version` incremented, and the conservation quantities of §2.8 are kept balanced. The specific cascades — listing withdrawal declining applications and voiding their agreements, an agreement void refunding a funded settlement and cancelling its scheduled appointment, and a dispute resolution terminating an agreement and refunding its deposit — are described in the workflow subsections of §3, where the full depth of each cascade is enumerated.

## 3. Business Logic & Workflows

### 3.1. Parties and the Master Lease

The marketplace begins with people. A `PlatformAdmin` onboards each `Landlord` and each `Leaseholder` with a display `name` and a contact `email`, and onboards each `Applicant` with a `name`, an `email`, a self-reported gross `annual_income_cents`, an optional `monthly_debt_cents` figure for recurring obligations that defaults to 0 when omitted, and a self-reported `credit_score`. Income and debt must be zero or greater, and the credit score must fall within the inclusive range 300 to 850; anything outside these bounds is an `ERR_VALIDATION`. Every applicant also carries a computed `active_application_count`, which begins at 0 and always reflects how many of that applicant's applications are currently in a non-terminal status.

A `Landlord` records a master lease for a unit they own. Creating a lease requires the acting landlord's `X-User-ID` to equal the `landlord_id` on the new record, and names the current tenant through `leaseholder_id`. The lease captures the master `monthly_rent_cents` (which must be greater than 0), the `security_deposit_cents` (zero or greater), the term boundaries `term_start_date` and `term_end_date`, and two permission flags, `allows_sublet` and `allows_assignment`, each defaulting to false when omitted. The `term_end_date` must be strictly after the `term_start_date`; otherwise the lease is rejected with `ERR_LEASE_DATES_INVALID` (HTTP 422). A freshly created lease begins in `UNVERIFIED` status with an `active_occupancy_count` of 0.

Before a lease can support any listing it must pass compliance verification. The owning landlord submits the lease for review, moving it from `UNVERIFIED` to `PENDING_REVIEW`; submitting a lease that is not currently `UNVERIFIED` is rejected with `ERR_LEASE_NOT_VERIFIABLE`. A `ComplianceOfficer` then records a `decision` of either `VERIFIED` or `REJECTED`, moving the lease from `PENDING_REVIEW` to `VERIFIED` or to the terminal `REJECTED` state respectively; a verify decision on a lease not in `PENDING_REVIEW` is rejected with `ERR_LEASE_NOT_PENDING_REVIEW`.

A verified lease's commercial terms can still change. The owning landlord may amend a `VERIFIED` lease, supplying a new `monthly_rent_cents`, a new `security_deposit_cents`, or both. Both fields are optional; an omitted field leaves its current value unchanged, and the amendment proceeds (incrementing the lease's `version`) even when neither field is supplied. An amendment keeps the lease in `VERIFIED` but increments the lease's `version` by 1, which is what invalidates any stale client view a downstream agreement draft might have relied upon. The lease `status` therefore progresses through `UNVERIFIED`, `PENDING_REVIEW`, and either `VERIFIED` or terminal `REJECTED`. Leases can be listed and filtered by `landlord_id`, `leaseholder_id`, or `status`.

### 3.2. Listing a Unit for Sublet or Takeover

Once a lease is verified, its `Leaseholder` advertises the unit. Creating a listing requires the acting leaseholder to own the referenced lease (identified by `lease_id`) and specifies the `listing_type` — either `SUBLET`, where a subtenant pays an advertised `asking_rent_cents`, or `TAKEOVER`, where an assignee steps into the master lease at its own rent. A listing declares the occupancy window it offers through `available_from` and an inclusive `available_to`, where `available_to` must be strictly after `available_from`, else `ERR_INVALID_DATE_RANGE` (HTTP 422). The listing also carries `min_term_months`, the minimum occupancy term in whole months, defaulting to 1 and never less than 1; a `screening_policy` of either `STANDARD` or `STRICT` that defaults to `STANDARD`; and an optional `landlord_approval_note`, which starts empty and is later populated by the landlord on approval or decline. The `asking_rent_cents` must be greater than 0. A new listing starts in `DRAFT`.

From `DRAFT`, the leaseholder requests landlord approval, which advances the listing to `PENDING_APPROVAL`. This transition carries three preconditions evaluated together: the listing must currently be `DRAFT` (else `ERR_LISTING_NOT_DRAFT`), the underlying lease must be `VERIFIED` (else `ERR_LEASE_NOT_VERIFIED`), and the requested `listing_type` must be permitted by the lease's flags — a `SUBLET` requires `allows_sublet` to be true and a `TAKEOVER` requires `allows_assignment` to be true, else `ERR_LISTING_TYPE_NOT_ALLOWED`.

The `Landlord` who owns the lease then either approves or declines, and may attach a `landlord_approval_note` on the way. Approval moves the listing from `PENDING_APPROVAL` to `OPEN`; a decline moves it to the terminal `DECLINED` state. Both actions require the listing to be `PENDING_APPROVAL`, else `ERR_LISTING_NOT_PENDING_APPROVAL`. An `OPEN` listing is discoverable by applicants. When an agreement on the listing reaches EXECUTED, the platform automatically advances the listing from `OPEN` to `MATCHED`; when that executed agreement later reaches COMPLETED, the platform advances it from `MATCHED` to terminal `CLOSED`. Listings may be listed and filtered by `lease_id` or `status`.

The leaseholder can withdraw a listing at any non-terminal point — that is, from `DRAFT`, `PENDING_APPROVAL`, `OPEN`, or `MATCHED` — moving it to terminal `WITHDRAWN`. Attempting to withdraw a listing already in `CLOSED`, `DECLINED`, or `WITHDRAWN` is rejected with `ERR_LISTING_NOT_WITHDRAWABLE`. Withdrawal triggers a three-level cascade. First, every application on the listing whose status is `SUBMITTED`, `SCREENING`, `INFO_REQUESTED`, `SCREENED`, or `MATCHED` is moved to `DECLINED`. Second, each such application's non-terminal agreement — one in `DRAFT`, `PENDING_SIGNATURES`, or `EXECUTED` — is moved to `VOID`. Third, for each voided agreement, if its settlement was `FUNDED` the settlement is moved to `REFUNDED` and its held deposit is released from escrow, and if the voided agreement had been `EXECUTED` (and thus occupying) the lease's `active_occupancy_count` is decremented by 1; additionally, any `SCHEDULED` handoff appointment on a voided agreement is moved to `CANCELLED`.

### 3.3. Applications, the Screening Loop, and Income Qualification

An `Applicant` applies to an `OPEN` listing, supplying the `listing_id`, their own `applicant_id`, and the occupancy window they propose through `proposed_move_in_date` and an inclusive `proposed_move_out_date`. The application is created in `SUBMITTED` status with a `screening_result` of `PENDING`, and the applicant's `active_application_count` is incremented by 1. Several gates guard creation: the listing must be `OPEN` (else `ERR_LISTING_NOT_OPEN`); the applicant must not already hold a non-terminal application on the same listing (else `ERR_DUPLICATE_APPLICATION`); the proposed window must be a valid range with `proposed_move_out_date` after `proposed_move_in_date` (else `ERR_INVALID_DATE_RANGE`, 422); the proposed occupancy must fall entirely within the listing's inclusive `available_from`-to-`available_to` window (else `ERR_OUTSIDE_AVAILABILITY_WINDOW`, 422); and the proposed term must be at least the listing's `min_term_months` (else `ERR_TERM_TOO_SHORT`, 409). The proposed term in whole months is the count of elapsed whole calendar months over the inclusive occupancy interval, computed by advancing from `proposed_move_in_date` to the exclusive end (`proposed_move_out_date` plus one day): it is the number of month boundaries between them, less one if the exclusive end's day-of-month is earlier than the move-in day-of-month. Applications can be listed and filtered by `listing_id`, `applicant_id`, or `status`.

Screening is a loop driven by compliance. A `ComplianceOfficer` starts screening, moving the application from `SUBMITTED` to `SCREENING` (else `ERR_APPLICATION_NOT_SCREENABLE`). While `SCREENING`, the officer may request additional information, moving the application to `INFO_REQUESTED` (else `ERR_APPLICATION_NOT_IN_SCREENING`); the `Applicant` then resubmits, returning the application from `INFO_REQUESTED` to `SCREENING` (else `ERR_APPLICATION_NOT_INFO_REQUESTED`). This `SCREENING` ⇄ `INFO_REQUESTED` cycle may repeat any number of rounds.

To conclude screening, the officer records a screening report against an application that is in `SCREENING` (else `ERR_APPLICATION_NOT_IN_SCREENING`), supplying the verified `credit_score` and an `income_verified` flag. The supplied `credit_score` must be an integer within the inclusive range 300 to 850 and `income_verified` must be a boolean, else `ERR_VALIDATION`. Recording the report creates a `ScreeningReport`, advances the application from `SCREENING` to `SCREENED`, and computes the income qualification. The report snapshots several system fields at that moment: the `applicant_annual_income_cents` copied from the applicant, the `effective_monthly_rent_cents` the applicant would actually pay, the `screening_policy` copied from the listing, and the three computed outputs `affordability_ratio`, `income_multiple`, and `qualification_result`. The report also stores its own `credit_score` and `income_verified` as supplied, and references the screened application by `application_id`.

The `effective_monthly_rent_cents` is the listing's `asking_rent_cents` when the listing type is `SUBLET`, and the lease's `monthly_rent_cents` when the listing type is `TAKEOVER`. From it, the platform derives two figures. The `affordability_ratio` is twelve times the effective monthly rent divided by the applicant's annual income, rounded half up to four decimal places. The `income_multiple` is the applicant's annual income divided by the effective monthly rent, rounded half up to four decimal places. When the applicant's `annual_income_cents` is 0, division is undefined and the platform instead stores an `affordability_ratio` of 9999.9999 and an `income_multiple` of 0, which yields `FAIL` under either policy.

Which figure decides the outcome depends on the report's `screening_policy`, and the two variants can disagree for identical inputs. Under the `STANDARD` policy, the qualification uses the ratio variant: the `qualification_result` is `PASS` when the affordability ratio is at most the maximum rent-to-income ratio of 0.35, and `FAIL` otherwise — equivalently, income of roughly 34.29 times monthly rent or more passes. Under the `STRICT` policy, the qualification uses the income-multiple variant: the result is `PASS` when the income multiple is at least 40, and `FAIL` otherwise — that is, annual income of at least forty times monthly rent. The strict variant is the tighter of the two and diverges from standard for incomes in the band between roughly 34.29 and 40 times rent. The comparison itself is performed at full precision, before the four-decimal rounding that is stored on the report. The resulting `qualification_result` is mirrored onto the application's `screening_result`, which is what later gates matching. Screening reports for an application can be listed via a reverse lookup by application.

A `ComplianceOfficer` matches a screened applicant, moving the application from `SCREENED` to terminal `MATCHED`. Matching has three preconditions: the application must be `SCREENED` (else `ERR_APPLICATION_NOT_SCREENED`), its `screening_result` must be `PASS` (else `ERR_SCREENING_NOT_PASSED`), and the listing must still be `OPEN` (else `ERR_LISTING_NOT_OPEN`). Compliance may also decline an application, and the applicant may withdraw one, from any non-terminal status (`SUBMITTED`, `SCREENING`, `INFO_REQUESTED`, or `SCREENED`); either action moves it to terminal `DECLINED` or `WITHDRAWN` respectively and decrements the applicant's `active_application_count` by 1. Attempting to decline or withdraw an application that is already `MATCHED`, `DECLINED`, or `WITHDRAWN` is rejected with `ERR_APPLICATION_NOT_ACTIONABLE`.

### 3.4. Drafting the Agreement and Auto-Creating the Settlement

With a matched application in hand, the owning `Leaseholder` drafts an agreement. The draft names the matched application through `application_id`, restates the negotiated occupancy through `occupancy_start_date` and an inclusive `occupancy_end_date`, and carries `expected_listing_version` for the concurrency check of §2.6. Several preconditions apply in the order of §2.9: the application must be `MATCHED` (else `ERR_APPLICATION_NOT_MATCHED`), its `screening_result` must be `PASS` (else `ERR_SCREENING_NOT_PASSED`), the occupancy window must be a valid range (else `ERR_INVALID_DATE_RANGE`), and the occupancy interval must not overlap any EXECUTED or ACTIVE agreement already on the same lease. Overlap is judged on the closed interval, so two occupancies that merely touch at an endpoint still conflict; a collision yields `ERR_OCCUPANCY_OVERLAP` (409). Finally the `expected_listing_version` must equal the listing's current `version`, else `ERR_STALE_LISTING_VERSION` (412).

A successful draft is created in `DRAFT` status with `agreement_type`, `listing_id`, and `lease_id` copied from the application's listing and lease. As a supersession side effect, any prior non-terminal agreement on the same listing is moved to `VOID`, and the listing's `version` is incremented by 1. The agreement records its `required_signer_roles` as the fixed set of `LANDLORD`, `LEASEHOLDER`, and `APPLICANT`; its `collected_signer_roles` (the distinct signer roles present so far) and its `is_fully_signed` flag are computed and begin empty and false.

Drafting also auto-creates the agreement's `Settlement` in `PENDING` status, with all of its financial fields computed up front. The settlement copies `agreement_type` from the agreement and references it through `agreement_id`. Its `base_monthly_rent_cents` is the listing's `asking_rent_cents` for a `SUBLET` and the lease's `monthly_rent_cents` for a `TAKEOVER`. The `deposit_amount_cents` is the smaller of the lease's `security_deposit_cents` and twice the base monthly rent — the deposit cap multiple of 2 protects the applicant from an excessive hold. The `last_month_rent_cents` is the base monthly rent for a `TAKEOVER` and 0 for a `SUBLET`.

The provisional first-period rent, stored as `prorated_first_rent_cents`, is prorated from the `occupancy_start_date`. Proration counts the move-in day as occupied: the number of days remaining in the move-in month is the total number of calendar days in that month, minus the day-of-month of the move-in date, plus one. The provisional rent is the base monthly rent multiplied by those remaining days, divided by the total number of days in that month, rounded half up to whole cents. At creation the `final_prorated_first_rent_cents` is 0; it stays 0 until the actual key handoff recomputes it.

The `platform_fee_cents` is the sum of two independently rounded components: a service component equal to 10% of the provisional `prorated_first_rent_cents`, rounded half up to whole cents, plus a processing component equal to 3% of the `deposit_amount_cents`, rounded half up to whole cents. Each component is rounded before they are added, per §2.7. The `total_move_in_cents` — the amount the applicant must fund — is the sum of the provisional `prorated_first_rent_cents`, the `deposit_amount_cents`, the `last_month_rent_cents`, and the `platform_fee_cents`. The settlement's `funded_amount_cents` is supplied later at funding time, and `deposit_held_cents` is 0 while the settlement is `PENDING`. Agreements can be listed and filtered by `application_id`, `listing_id`, or `lease_id`, or `status`; settlements can be listed and filtered by `agreement_id` or `status`.

### 3.5. Collecting Signatures and Executing the Agreement

A draft agreement must gather three signatures before it takes effect. The owning `Leaseholder` first sends the draft for signature, moving it from `DRAFT` to `PENDING_SIGNATURES` (else `ERR_AGREEMENT_NOT_DRAFT`). While the agreement is `PENDING_SIGNATURES`, each of the three parties e-signs by declaring their `signer_role`; a signature attempt on an agreement not in `PENDING_SIGNATURES` is rejected with `ERR_AGREEMENT_NOT_PENDING_SIGNATURES`. The acting role must match the declared `signer_role` and that role must belong to the required set — a `Landlord` may only sign as `LANDLORD`, a `Leaseholder` as `LEASEHOLDER`, and an `Applicant` as `APPLICANT` — else `ERR_INVALID_SIGNER_ROLE`. A role that has already signed cannot sign again; a repeat is rejected with `ERR_DUPLICATE_SIGNATURE`. Each signature records the `agreement_id`, the `signer_role`, the `signer_id` taken from the caller's `X-User-ID`, and a `signed_at` stamped from the logical clock. The agreement's `collected_signer_roles` grows as distinct roles sign, and `is_fully_signed` becomes true once the collected roles cover the required set. Signatures for an agreement can be listed by a reverse lookup on the agreement.

When the final required signature lands and `is_fully_signed` becomes true, the platform automatically advances the agreement from `PENDING_SIGNATURES` to `EXECUTED`, advances the listing to `MATCHED`, and increments the lease's `active_occupancy_count` by 1 to reserve the occupancy slot. This is the moment the occupancy interval becomes a live reservation that later overlap checks must respect.

An executed agreement is activated by the owning `Leaseholder`, moving it from `EXECUTED` to `ACTIVE`. Activation requires the agreement to be `EXECUTED` (else `ERR_AGREEMENT_NOT_EXECUTED`) and its settlement to be `FUNDED` (else `ERR_SETTLEMENT_NOT_FUNDED`). Later, when the term is served, either the owning `Leaseholder` or a `ComplianceOfficer` completes an `ACTIVE` agreement, moving it to terminal `COMPLETED`; completion requires the agreement to be `ACTIVE` (else `ERR_AGREEMENT_NOT_ACTIVE`) and its settlement to be `HANDED_OFF` (else `ERR_SETTLEMENT_NOT_HANDED_OFF`, the settlement not yet being in a completable state). Completion cascades: the settlement moves to `RELEASED` and its held deposit leaves escrow back to the landlord/leaseholder side, the lease's `active_occupancy_count` decrements by 1, and the listing moves to terminal `CLOSED`.

The owning `Leaseholder` may also void an agreement while it is `DRAFT`, `PENDING_SIGNATURES`, or `EXECUTED`, moving it to terminal `VOID`; a void attempt on any other status is rejected with `ERR_AGREEMENT_NOT_VOIDABLE`. Voiding cascades in step with §2.8: if the settlement is `FUNDED` it moves to `REFUNDED` and its deposit leaves escrow back to the applicant; if the agreement had been `EXECUTED`, the lease's `active_occupancy_count` decrements by 1; and any `SCHEDULED` handoff appointment on the agreement moves to `CANCELLED`. (A void may also be triggered by the platform when a listing is withdrawn or when a newer draft supersedes an earlier one, with the same settlement, occupancy, and appointment consequences.)

### 3.6. Funding, Key Handoff, and Deposit Release

The `Applicant` funds the settlement, tendering `funded_amount_cents`. Funding requires the settlement to be `PENDING` (else `ERR_SETTLEMENT_NOT_PENDING`) and the tendered `funded_amount_cents` to equal the settlement's `total_move_in_cents` exactly; a mismatch is rejected with `ERR_FUNDING_AMOUNT_MISMATCH` (HTTP 402). On success the settlement moves from `PENDING` to `FUNDED`, and `deposit_held_cents` is set to `deposit_amount_cents`, adding the deposit to platform escrow.

After the agreement is active, the owning `Leaseholder` confirms the physical key handoff, supplying the actual `handoff_date`. Handoff requires the settlement to be `FUNDED` (else `ERR_SETTLEMENT_NOT_FUNDED`) and the parent agreement to be `ACTIVE` (else `ERR_AGREEMENT_NOT_ACTIVE`). It moves the settlement from `FUNDED` to `HANDED_OFF` and records the `handoff_date`. Crucially, handoff recomputes the first-period rent from the actual move-in day: the `final_prorated_first_rent_cents` is the base monthly rent multiplied by the days remaining in the handoff month (days in that month minus the handoff day-of-month plus one, counting the handoff day), divided by the days in that month, rounded half up. Because the real handoff date may differ from the originally assumed `occupancy_start_date`, this final figure may differ from the provisional `prorated_first_rent_cents`.

A `ComplianceOfficer` may release a handed-off deposit, moving the settlement from `HANDED_OFF` to terminal `RELEASED` and setting `deposit_held_cents` to 0, removing the amount from escrow; a release attempt on a settlement not in `HANDED_OFF` is rejected with `ERR_SETTLEMENT_NOT_HANDED_OFF`. Release also happens automatically when the parent agreement completes (§3.5). The settlement lifecycle thus runs `PENDING` → `FUNDED` → `HANDED_OFF` → `RELEASED`, with `REFUNDED` reachable from `FUNDED` or `HANDED_OFF` when the parent agreement is voided or terminated, and `FORFEITED` reachable from `HANDED_OFF` on a leaseholder-favouring dispute.

### 3.7. The Landlord's Handoff Calendar

Key handoffs are scheduled as appointments on the owning landlord's calendar. A `Landlord` schedules a handoff appointment against an agreement (named by `agreement_id`), giving a `scheduled_start` and a `scheduled_end` as ISO 8601 UTC instants, where `scheduled_end` must be after `scheduled_start` (else `ERR_INVALID_DATE_RANGE`, 422). The appointment's `landlord_id` is denormalized from the agreement's lease so the platform knows whose calendar it belongs to. Scheduling requires the agreement to be `EXECUTED` or `ACTIVE` (else `ERR_AGREEMENT_NOT_READY_FOR_HANDOFF`). The appointment must also clear a two-hour buffer: its time must not fall within 120 minutes of any other `SCHEDULED` appointment on the same landlord's calendar. If the new appointment sits closer than that buffer to an existing scheduled one, it is rejected with `ERR_APPOINTMENT_CONFLICT` (409). Proximity is measured between the two appointments' intervals: the new appointment clears only if it ends at least 120 minutes before the existing appointment starts, or starts at least 120 minutes after the existing appointment ends; any smaller separation — including a direct overlap — conflicts, while a separation of exactly 120 minutes clears. A new appointment is created in `SCHEDULED` status.

The `Landlord` marks a scheduled appointment completed (moving it from `SCHEDULED` to terminal `COMPLETED`) or cancels it (moving it from `SCHEDULED` to terminal `CANCELLED`); either action requires the appointment to be `SCHEDULED`, else `ERR_APPOINTMENT_NOT_SCHEDULED`. The platform itself cancels scheduled appointments when their agreement is voided or terminated. Appointments can be listed and filtered by `agreement_id` or `landlord_id`, or `status`.

### 3.8. Disputes and Their Resolution

Once an agreement is `ACTIVE`, either the owning `Leaseholder` or the `Applicant` may file a dispute, naming the `agreement_id`, declaring who is filing through `raised_by` (either `LEASEHOLDER` or `APPLICANT`), and giving a free-text `reason`. Filing requires the agreement to be `ACTIVE`, else `ERR_AGREEMENT_NOT_ACTIVE`. A new dispute begins in `FILED` status with a null `outcome` and a `resolution_amount_cents` that defaults to 0. Disputes can be listed and filtered by `agreement_id` or `status`.

A `ComplianceOfficer` opens review, moving the dispute from `FILED` to `UNDER_REVIEW` (else `ERR_DISPUTE_NOT_FILED`), and then resolves it by supplying an `outcome` and an optional `resolution_amount_cents` (defaulting to 0, which is recorded on the dispute's `resolution_amount_cents` for every outcome even where it carries no settlement consequence). Resolution requires the dispute to be `UNDER_REVIEW` (else `ERR_DISPUTE_NOT_UNDER_REVIEW`), and the `outcome` must be one of `RESOLVED_LEASEHOLDER`, `RESOLVED_APPLICANT`, `RESOLVED_SPLIT`, or `DISMISSED`, else `ERR_INVALID_DISPUTE_OUTCOME` (422). The four outcomes carry distinct consequences, and each moves the dispute's `status` to the matching terminal state while recording the same value in its `outcome`:

- **`RESOLVED_APPLICANT`** favours the incoming occupant and unwinds the tenancy. The parent agreement cascades to terminal `TERMINATED`; that termination in turn moves the settlement to `REFUNDED` (the deposit is returned to the applicant and leaves escrow), decrements the lease's `active_occupancy_count` by 1, and moves the listing to terminal `CLOSED`.
- **`RESOLVED_LEASEHOLDER`** favours the original tenant. If the supplied `resolution_amount_cents` equals the settlement's `deposit_amount_cents` and the settlement is `HANDED_OFF`, the settlement moves to `FORFEITED` — the deposit is forfeited to the leaseholder and leaves escrow — while the agreement remains `ACTIVE`.
- **`RESOLVED_SPLIT`** records the supplied `resolution_amount_cents` as the leaseholder's share for manual reconciliation off-platform; there is no settlement state change and the agreement remains `ACTIVE`.
- **`DISMISSED`** closes the dispute with no financial effect; the agreement remains `ACTIVE`.

### 3.9. Platform Fees

Beyond the platform fee folded into a settlement's move-in total, the platform records ad-hoc fees against agreements. A `PlatformAdmin` records a fee naming the `agreement_id`, a `fee_type` of `PLATFORM`, `SCREENING`, `CANCELLATION`, or `LATE`, and an `amount_cents` that must be zero or greater. A new fee starts in `PENDING`. From `PENDING`, the admin either charges the fee (moving it to terminal `CHARGED`) or waives it (moving it to terminal `WAIVED`); both require the fee to be `PENDING`, else `ERR_FEE_NOT_PENDING`. A `CHARGED` fee may later be refunded, moving it to terminal `REFUNDED`; a refund requires the fee to be `CHARGED`, else `ERR_FEE_NOT_CHARGED`. Fees can be listed and filtered by `agreement_id` or `status`.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return `201 Created`. Operations that modify an existing resource — including all state-transition actions and all reads — return `200 OK`. All endpoints require the `X-User-ID` and `X-User-Role` headers of §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | PlatformAdmin, ComplianceOfficer |
| POST | `/landlords` | Onboard a landlord | PlatformAdmin |
| GET | `/landlords/{landlordId}` | Get landlord | Landlord, Leaseholder, Applicant, ComplianceOfficer, PlatformAdmin |
| POST | `/leaseholders` | Onboard a leaseholder | PlatformAdmin |
| GET | `/leaseholders/{leaseholderId}` | Get leaseholder | Landlord, Leaseholder, Applicant, ComplianceOfficer, PlatformAdmin |
| POST | `/applicants` | Onboard an applicant | PlatformAdmin |
| GET | `/applicants/{applicantId}` | Get applicant | Landlord, Leaseholder, Applicant, ComplianceOfficer, PlatformAdmin |
| POST | `/leases` | Create a master lease | Landlord |
| GET | `/leases/{leaseId}` | Get lease | Landlord, Leaseholder, Applicant, ComplianceOfficer, PlatformAdmin |
| GET | `/leases` | List leases (filter by landlord or leaseholder) | Landlord, Leaseholder, Applicant, ComplianceOfficer, PlatformAdmin |
| POST | `/leases/{leaseId}/submit-verification` | Submit lease for verification | Landlord |
| POST | `/leases/{leaseId}/verify` | Verify or reject a lease | ComplianceOfficer |
| POST | `/leases/{leaseId}/amend` | Amend verified lease terms | Landlord |
| POST | `/listings` | Create a listing on a verified lease | Leaseholder |
| GET | `/listings/{listingId}` | Get listing | Landlord, Leaseholder, Applicant, ComplianceOfficer, PlatformAdmin |
| GET | `/listings` | List listings (filter by lease) | Landlord, Leaseholder, Applicant, ComplianceOfficer, PlatformAdmin |
| POST | `/listings/{listingId}/request-approval` | Request landlord approval | Leaseholder |
| POST | `/listings/{listingId}/approve` | Approve the listing | Landlord |
| POST | `/listings/{listingId}/decline` | Decline the listing | Landlord |
| POST | `/listings/{listingId}/withdraw` | Withdraw the listing (cascade) | Leaseholder |
| POST | `/applications` | Apply to an OPEN listing | Applicant |
| GET | `/applications/{applicationId}` | Get application | Landlord, Leaseholder, Applicant, ComplianceOfficer, PlatformAdmin |
| GET | `/applications` | List applications (filter by listing or applicant) | Landlord, Leaseholder, Applicant, ComplianceOfficer, PlatformAdmin |
| POST | `/applications/{applicationId}/start-screening` | Begin screening | ComplianceOfficer |
| POST | `/applications/{applicationId}/request-info` | Request additional info | ComplianceOfficer |
| POST | `/applications/{applicationId}/resubmit-info` | Resubmit info (returns to screening) | Applicant |
| POST | `/applications/{applicationId}/screening-report` | Record screening report and outcome | ComplianceOfficer |
| GET | `/applications/{id}/screening-report` | List screening reports for an application | Landlord, Leaseholder, Applicant, ComplianceOfficer, PlatformAdmin |
| POST | `/applications/{applicationId}/match` | Match a screened, passing applicant | ComplianceOfficer |
| POST | `/applications/{applicationId}/decline` | Decline an application | ComplianceOfficer |
| POST | `/applications/{applicationId}/withdraw` | Withdraw an application | Applicant |
| POST | `/agreements` | Draft an agreement (OCC; supersedes prior draft) | Leaseholder |
| GET | `/agreements/{agreementId}` | Get agreement | Landlord, Leaseholder, Applicant, ComplianceOfficer, PlatformAdmin |
| GET | `/agreements` | List agreements (filter by application, listing, or lease) | Landlord, Leaseholder, Applicant, ComplianceOfficer, PlatformAdmin |
| POST | `/agreements/{agreementId}/send-for-signature` | Move a draft into signature collection | Leaseholder |
| POST | `/agreements/{agreementId}/signatures` | E-sign the agreement | Landlord, Leaseholder, Applicant |
| GET | `/agreements/{id}/signatures` | List signatures for an agreement | Landlord, Leaseholder, Applicant, ComplianceOfficer, PlatformAdmin |
| POST | `/agreements/{agreementId}/activate` | Activate an executed agreement | Leaseholder |
| POST | `/agreements/{agreementId}/complete` | Complete an active agreement | Leaseholder, ComplianceOfficer |
| POST | `/agreements/{agreementId}/void` | Void a non-active agreement | Leaseholder |
| GET | `/settlements/{settlementId}` | Get settlement | Landlord, Leaseholder, Applicant, ComplianceOfficer, PlatformAdmin |
| GET | `/settlements` | List settlements (filter by agreement) | Landlord, Leaseholder, Applicant, ComplianceOfficer, PlatformAdmin |
| POST | `/settlements/{settlementId}/fund` | Fund deposit + first period + fee | Applicant |
| POST | `/settlements/{settlementId}/handoff` | Confirm key handoff (final proration) | Leaseholder |
| POST | `/settlements/{settlementId}/release` | Release the deposit | ComplianceOfficer |
| POST | `/handoff-appointments` | Schedule a key-handoff appointment | Landlord |
| GET | `/handoff-appointments/{appointmentId}` | Get appointment | Landlord, Leaseholder, Applicant, ComplianceOfficer, PlatformAdmin |
| GET | `/handoff-appointments` | List appointments (filter by agreement or landlord) | Landlord, Leaseholder, Applicant, ComplianceOfficer, PlatformAdmin |
| POST | `/handoff-appointments/{appointmentId}/complete` | Mark appointment completed | Landlord |
| POST | `/handoff-appointments/{appointmentId}/cancel` | Cancel appointment | Landlord |
| POST | `/disputes` | File a dispute on an active agreement | Leaseholder, Applicant |
| GET | `/disputes/{disputeId}` | Get dispute | Landlord, Leaseholder, Applicant, ComplianceOfficer, PlatformAdmin |
| GET | `/disputes` | List disputes (filter by agreement) | Landlord, Leaseholder, Applicant, ComplianceOfficer, PlatformAdmin |
| POST | `/disputes/{disputeId}/review` | Open review | ComplianceOfficer |
| POST | `/disputes/{disputeId}/resolve` | Resolve the dispute (branching outcomes) | ComplianceOfficer |
| POST | `/fees` | Record a fee against an agreement | PlatformAdmin |
| GET | `/fees/{feeId}` | Get fee | Landlord, Leaseholder, Applicant, ComplianceOfficer, PlatformAdmin |
| GET | `/fees` | List fees (filter by agreement) | Landlord, Leaseholder, Applicant, ComplianceOfficer, PlatformAdmin |
| POST | `/fees/{feeId}/charge` | Charge a pending fee | PlatformAdmin |
| POST | `/fees/{feeId}/waive` | Waive a pending fee | PlatformAdmin |
| POST | `/fees/{feeId}/refund` | Refund a charged fee | PlatformAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_VALIDATION` | 400 |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_OWNERSHIP_VIOLATION` | 403 |
| `ERR_LANDLORD_NOT_FOUND` | 404 |
| `ERR_LEASEHOLDER_NOT_FOUND` | 404 |
| `ERR_APPLICANT_NOT_FOUND` | 404 |
| `ERR_LEASE_NOT_FOUND` | 404 |
| `ERR_LISTING_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_AGREEMENT_NOT_FOUND` | 404 |
| `ERR_SETTLEMENT_NOT_FOUND` | 404 |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 |
| `ERR_DISPUTE_NOT_FOUND` | 404 |
| `ERR_FEE_NOT_FOUND` | 404 |
| `ERR_LEASE_NOT_VERIFIABLE` | 409 |
| `ERR_LEASE_NOT_PENDING_REVIEW` | 409 |
| `ERR_LEASE_NOT_VERIFIED` | 409 |
| `ERR_LEASE_DATES_INVALID` | 422 |
| `ERR_LISTING_TYPE_NOT_ALLOWED` | 409 |
| `ERR_LISTING_NOT_DRAFT` | 409 |
| `ERR_LISTING_NOT_PENDING_APPROVAL` | 409 |
| `ERR_LISTING_NOT_OPEN` | 409 |
| `ERR_LISTING_NOT_WITHDRAWABLE` | 409 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_DUPLICATE_APPLICATION` | 409 |
| `ERR_OUTSIDE_AVAILABILITY_WINDOW` | 422 |
| `ERR_TERM_TOO_SHORT` | 409 |
| `ERR_APPLICATION_NOT_SCREENABLE` | 409 |
| `ERR_APPLICATION_NOT_IN_SCREENING` | 409 |
| `ERR_APPLICATION_NOT_INFO_REQUESTED` | 409 |
| `ERR_APPLICATION_NOT_SCREENED` | 409 |
| `ERR_APPLICATION_NOT_MATCHED` | 409 |
| `ERR_SCREENING_NOT_PASSED` | 409 |
| `ERR_APPLICATION_NOT_ACTIONABLE` | 409 |
| `ERR_STALE_LISTING_VERSION` | 412 |
| `ERR_OCCUPANCY_OVERLAP` | 409 |
| `ERR_AGREEMENT_NOT_DRAFT` | 409 |
| `ERR_AGREEMENT_NOT_PENDING_SIGNATURES` | 409 |
| `ERR_INVALID_SIGNER_ROLE` | 409 |
| `ERR_DUPLICATE_SIGNATURE` | 409 |
| `ERR_AGREEMENT_NOT_EXECUTED` | 409 |
| `ERR_SETTLEMENT_NOT_FUNDED` | 409 |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 |
| `ERR_AGREEMENT_NOT_VOIDABLE` | 409 |
| `ERR_SETTLEMENT_NOT_PENDING` | 409 |
| `ERR_FUNDING_AMOUNT_MISMATCH` | 402 |
| `ERR_SETTLEMENT_NOT_HANDED_OFF` | 409 |
| `ERR_AGREEMENT_NOT_READY_FOR_HANDOFF` | 409 |
| `ERR_APPOINTMENT_CONFLICT` | 409 |
| `ERR_APPOINTMENT_NOT_SCHEDULED` | 409 |
| `ERR_DISPUTE_NOT_FILED` | 409 |
| `ERR_DISPUTE_NOT_UNDER_REVIEW` | 409 |
| `ERR_INVALID_DISPUTE_OUTCOME` | 422 |
| `ERR_FEE_NOT_PENDING` | 409 |
| `ERR_FEE_NOT_CHARGED` | 409 |
</content>
</invoke>
