# Sign & Billboard Zoning Permit API — Product Requirements Document

## 1. Introduction

Municipal sign and billboard regulation is a domain where a handful of dimensional numbers — a face area, a setback, an illumination class — collide with a layered approval process, a fee schedule, and a body of grandfathered signage that predates the current code. This document specifies the API that a planning department uses to administer that regime end to end: intake of a sign application against a specific zoning parcel, the parallel dimensional and overlay reviews that a sign must survive, the variance machinery through which an applicant can seek relief from a by-right standard, the issuance and payment of the permit itself, field inspection, and the enforcement track of violations and removal orders. Alongside the sign track, the same platform registers freestanding billboard structures, meters their registration fees by advertising face, and manages exclusive advertising leases against each structure.

The system serves four constituencies whose duties are deliberately separated: applicants and billboard operators who file and pay; planning staff who review, decide, and enforce; a zoning board of appeals that rules on variances independently of the staff member who recommended them; and field inspectors who record outcomes on the signs assigned to them. Because permits expire, registrations lapse, cure periods run out, and non-conforming signs amortize toward zero, the platform is driven by a logical clock: time does not pass on its own, but is advanced explicitly, and each advance sweeps every time-based transition into its correct state. The remainder of this document defines the global contracts every endpoint honours (Section 2) and then walks the business workflows in detail (Section 3), before cataloguing the endpoints (Section 4) and error codes (Section 5).

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply uniformly across the entire API.

### 2.1. User and Role-Based Access Control

Every request must be authenticated through two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. A request missing either header, or carrying a malformed value, is rejected with `ERR_UNAUTHENTICATED`. When the headers are well-formed but the role is not permitted to perform the requested operation — or an ownership-scoped role acts on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED`.

The system recognizes exactly four roles, spelled precisely as follows: `Applicant`, `Planner`, `ZoningBoard`, and `Inspector`.

The `Applicant` role is entity-backed. When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant` record; ownership checks compare a resource's owning foreign key to `X-User-ID`. A sign application may only be created with an `applicant_id` equal to `X-User-ID`, a billboard may only be created with an `operator_id` equal to `X-User-ID`, and the applicant-driven actions on those resources and their descendants (submitting, filing variances, paying, renewing, registering, leasing, terminating) are scoped to the owning applicant.

The `Inspector` role is likewise entity-backed. When `X-User-Role` is `Inspector`, `X-User-ID` is the `id` of the acting `Inspector` record; an inspector may only record an outcome on an inspection whose `inspector_id` equals `X-User-ID`.

The `Planner` and `ZoningBoard` roles are both opaque operator identities. When `X-User-Role` is `Planner`, `X-User-ID` is an opaque staff identifier not tied to any persisted entity; the server records it where a transition captures a recommender (for example, as `recommended_by_user_id` on a `Variance`) but never compares it to any entity's `id`. When `X-User-Role` is `ZoningBoard`, `X-User-ID` is similarly an opaque board-member identifier; the server records it as `decided_by_user_id` on a `Variance` but does not resolve it to any stored record. The one place these two opaque identities interact is the segregation-of-duties rule on variance decisions, described in Section 3.3.

All four roles may call every read (GET) endpoint. Write endpoints are restricted as catalogued in Section 4.

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

### 2.3. Pagination

All list endpoints accept two optional query parameters, `limit` and `offset`. The `limit` parameter defaults to 10, must be at least 1, and may not exceed 100. The `offset` parameter defaults to 0 and represents the number of leading records to skip. List results are ordered by `created_at` ascending — that is, oldest record first. Each list response reports `limit`, `offset`, `total_count` (the total number of records matching the filter, before pagination), and `has_more` (a boolean that is true when records remain beyond the current page) inside the `meta` object.

### 2.4. Resource Identity, Timestamps, and Versioning

Every resource carries a server-minted `id`, which is a UUID with no type prefix and serves as identity only. Every resource also carries a `created_at` timestamp, an ISO 8601 UTC value with three fractional digits, fixed at the moment of creation.

Most resources additionally carry an `updated_at` timestamp and an integer `version`. The `version` begins at 1 on creation and increments by one on every mutation that changes the resource; `updated_at` is refreshed to the current logical instant on each such mutation. Four entity types are lightweight audit records that carry only `id` and `created_at` and therefore have **no** `updated_at` and **no** `version`: the zoning `Parcel`, the `Applicant`, the `Inspector`, and the `RemovalOrder`. Although a parcel has no `version`, its computed slot counters (described in Section 2.7) are always recomputed on read so that a fetched parcel reflects live state.

### 2.5. The Logical Clock and Deterministic Sweeps

The platform keeps a single logical clock rather than reading wall-clock time. Before any clock call is made, the server's clock reads `2026-05-01T00:00:00Z`. A planner advances the clock by supplying a target instant as `to_iso8601`; the clock is set to that instant. Every timestamp the system stamps on a record — a permit's `issued_at` and `activated_at`, a violation's `issued_at`, a registration's `registered_at`, and so on — is drawn from this logical clock, not from wall time.

Advancing the clock performs a deterministic sweep of every time-based transition, in addition to the read-time valuations described later:

- Any `ACTIVE` permit whose `expires_at` is at or before the new clock instant transitions to `EXPIRED`, releasing its parcel sign slot.
- Any `REGISTERED` billboard whose `registration_expires_at` is at or before the new instant transitions to `LAPSED`, and each of that billboard's leases currently in `ACTIVE` status cascades to `SUSPENDED`.
- Any `ACTIVE` billboard lease whose `end_date` is at or before the new instant transitions to `EXPIRED`.
- Any `ACTIVE` non-conforming registration whose elapsed time has reached its amortization term transitions to `AMORTIZED`.

Because the sweep is driven only by explicit clock advances, the same sequence of calls always produces the same states.

### 2.6. Optimistic Concurrency Control

Two create operations are guarded by optimistic concurrency control against a parent resource whose state legitimately drifts underneath a client.

Issuing a permit is guarded against the `SignApplication`. A permit-issuance request must carry `expected_application_version` holding the application `version` the client last observed. If that value does not equal the application's current `version` — because, for instance, a granted variance or a recorded review advanced the application and possibly changed its approved dimensions or fee after the client's read — the issuance is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from minting a permit against an application it has not seen in its current form.

Creating a billboard lease is guarded against the `Billboard`. A lease-creation request must carry `expected_billboard_version` holding the billboard `version` the client last observed. If another lease that occupies part of the calendar, or a registration renewal, has advanced the billboard's `version` since the client's read, the create is rejected with `ERR_STALE_VERSION` (HTTP 412), because the client's availability view is stale.

No other endpoint accepts a version field.

### 2.7. Fee Precision, Rounding, and the Parcel & Revenue Ledgers

All monetary amounts are integer cents. Wherever a fee formula produces a fractional cent it is rounded half up to the nearest whole cent. The two rounding sites are called out precisely in Section 3: the sign permit fee rounds the area component after summing its tiered pieces, and the billboard registration fee rounds **each face's** fee before the faces are summed — the per-face rounding order is load-bearing and must not be replaced by rounding a single product of base, multiplier, and face count.

Each parcel maintains two conserved integer counters. `active_permit_count` is the number of permits on that parcel currently in `ACTIVE` status; it starts at 0. `available_sign_slots` is `max_signs` minus `active_permit_count`. The invariant `active_permit_count` + `available_sign_slots` = `max_signs` holds at all times, and `available_sign_slots` is never negative. These counters move only when a permit activates, expires, is revoked, or is renewed out of the expired state, as detailed in Section 3.4.

The platform also conserves permit revenue in aggregate: the total permit revenue is the sum over all permits of `fee_charged_cents` minus `fee_refunded_cents`. A revoke refunds exactly the amount charged, so issuing a permit and then revoking it leaves this global sum unchanged relative to its value before the issue.

### 2.8. Validation Order and Error Precedence

When a single request could fail several checks, the checks are evaluated in a fixed priority order and the first failure determines the response. The order is:

1. **Authentication** — the `X-User-Role` and `X-User-ID` headers must be present and well-formed, else `ERR_UNAUTHENTICATED`.
2. **Authorization** — the acting role must be permitted for the endpoint, and an entity-backed role must own the target resource, else `ERR_UNAUTHORIZED`.
3. **Generic existence** — path- and body-referenced resources must exist, validated left to right; a missing generic resource yields `ERR_NOT_FOUND`.
4. **Typed existence** — for endpoints keyed on a typed root, a missing root yields the specific code `ERR_APPLICATION_NOT_FOUND`, `ERR_PARCEL_NOT_FOUND`, `ERR_PERMIT_NOT_FOUND`, or `ERR_BILLBOARD_NOT_FOUND`.
5. **Body well-formedness** — on every write, required fields must be present and correctly typed, numeric quantities must be non-negative, and enum values must be members of their allowed set; failures yield `ERR_VALIDATION`, or `ERR_INVALID_ENUM` for a bad enum value, or `ERR_INVALID_INTERVAL` for a lease whose `end_date` is not strictly after its `start_date`.
6. **State legality** — the target resource must be in a state from which the requested transition is legal, else `ERR_INVALID_STATE`.
7. **Referential state** — a referenced entity must be in the required state: an application must be `APPROVED` for permit issuance (`ERR_APPLICATION_NOT_APPROVED`), a billboard must be `REGISTERED` for a lease (`ERR_BILLBOARD_NOT_REGISTERED`), and a permit must be `ACTIVE` for inspection scheduling (`ERR_PERMIT_INACTIVE`).
8. **Segregation of duties** — on a variance decision, the deciding user must differ from the recommender, else `ERR_SEGREGATION_OF_DUTIES`.
9. **Dimensional and scheduling constraints** — the sign-dimension checks, lease-interval overlap, and inspector schedule conflict described in Section 3, yielding `ERR_SIGN_AREA_EXCEEDED`, `ERR_SIGN_HEIGHT_EXCEEDED`, `ERR_SETBACK_INSUFFICIENT`, `ERR_ILLUMINATION_NOT_ALLOWED`, `ERR_HISTORIC_OVERLAY_REVIEW_REQUIRED`, `ERR_LEASE_OVERLAP`, or `ERR_INSPECTION_OVERLAP`.
10. **Temporal gates** — renewal windows and the escalation cure period, yielding `ERR_RENEWAL_WINDOW_CLOSED` or `ERR_CURE_PERIOD_ACTIVE`.
11. **Fiscal sufficiency** — a payment or registration amount must cover the computed fee, else `ERR_FEE_NOT_PAID`.
12. **Slot quota** — activating a permit must not exceed the parcel's `max_signs`, else `ERR_SIGN_SLOTS_EXHAUSTED`.
13. **Optimistic concurrency** — the supplied `expected_application_version` or `expected_billboard_version` must match the parent's current `version`, else `ERR_STALE_VERSION`.

This ordering is normative: for example, an authorization failure is reported before a not-found, and a stale-version conflict is reported only after all earlier checks have passed.

## 3. Business Logic & Workflows

### 3.1. Foundational Records: Parcels, Applicants, and Inspectors

Before any sign can be proposed, a planner establishes the regulatory canvas. A zoning `Parcel` is created by a planner and captures the by-right standards for signage on that ground: its `zoning_district`, one of `COMMERCIAL`, `INDUSTRIAL`, `RESIDENTIAL`, or `MIXED_USE`; two optional overlay flags, `historic_overlay` and `corridor_overlay`, each defaulting to false when omitted; the dimensional ceilings `max_sign_area_sqft`, `max_height_ft`, and the floor `min_setback_ft`; the highest by-right illumination class `allowed_illumination` (one of `NONE`, `EXTERNAL`, or `DIGITAL_DISPLAY`); and `max_signs`, the number of concurrently active permitted signs the parcel may host. On creation, the parcel's `active_permit_count` is 0 and its `available_sign_slots` equals `max_signs`.

A planner also registers the participants. Creating an `Applicant` records its `name` and `contact_email`; the returned `id` is the value that person or company will present as `X-User-ID` when acting under the `Applicant` role. Creating an `Inspector` records its `name`; its `id` is the value the inspector will present as `X-User-ID`. Both of these records, like the parcel and the removal order, are lightweight — they carry only `id` and `created_at`.

### 3.2. Sign Applications and the Two Parallel Reviews

An applicant opens a `SignApplication` in `DRAFT` status, naming the `parcel_id` the sign will stand on, the `applicant_id` (which must equal the caller's `X-User-ID`), the `sign_type` (`WALL`, `MONUMENT`, or `DIGITAL`), and the requested dimensions `requested_area_sqft`, `requested_height_ft`, `requested_setback_ft`, and `requested_illumination` (`NONE`, `EXTERNAL`, or `DIGITAL_DISPLAY`). At creation both review axes begin at `PENDING`.

Submitting a draft advances the application from `DRAFT` to `SUBMITTED`, provided all requested dimension fields are present. Submission computes the provisional permit fee, `provisional_fee_cents`, from the requested values (the calculation is given in Section 3.4), and sets both `dimensional_review` and `overlay_review` to `PENDING`. From this point the application carries **two independent review axes** that evolve separately from one another and from the application's own `status`.

The **dimensional axis**, `dimensional_review`, moves through `PENDING`, `PASS`, and `FAIL`. A planner records a dimensional outcome; a `PASS` is only legal when every dimensional constraint is satisfied. The effective area under test is the granted AREA-variance value if an AREA variance for this application has been granted, otherwise `requested_area_sqft`; a `PASS` requires that this effective area be at most the parcel's `max_sign_area_sqft` (the ceiling is inclusive — equality passes), else `ERR_SIGN_AREA_EXCEEDED`. Likewise the effective height must be at most `max_height_ft`, else `ERR_SIGN_HEIGHT_EXCEEDED`; the `requested_setback_ft` must be at least the parcel's `min_setback_ft`, else `ERR_SETBACK_INSUFFICIENT`; and the requested illumination class must not outrank what the parcel allows, else `ERR_ILLUMINATION_NOT_ALLOWED`. Illumination is ranked `NONE` below `EXTERNAL` below `DIGITAL_DISPLAY` (numerically 0, 1, and 2); the check passes when the rank of `requested_illumination` is at most the rank of the parcel's `allowed_illumination`, unless an `ILLUMINATION` variance has been granted for the application, which lifts the ceiling. A planner may also record a dimensional `FAIL` outright, and — after variance relief makes the dimensions conform — may move the axis from `FAIL` back to `PASS`.

The **overlay axis**, `overlay_review`, moves through `PENDING`, `CLEARED`, `VARIANCE_REQUIRED`, and `VARIANCE_GRANTED`. A planner may clear the overlay only when the parcel is not in a historic overlay — that is, `historic_overlay` is false — or a `HISTORIC` variance has been granted for the application; clearing a historic-overlay parcel without that granted variance is rejected with `ERR_HISTORIC_OVERLAY_REVIEW_REQUIRED`. Alternatively the planner may mark the axis `VARIANCE_REQUIRED`, signalling that the applicant must obtain relief. The axis reaches `VARIANCE_GRANTED` not by direct planner action but as a system side effect when a `HISTORIC` or `ILLUMINATION` variance for the application is granted (see Section 3.3). The single review endpoint distinguishes which axis it acts on by its `review_type` input (`DIMENSIONAL` or `OVERLAY`) paired with the `outcome`.

A planner decides a submitted application by supplying a `decision`. An approval requires that `dimensional_review` be `PASS` **and** that `overlay_review` be either `CLEARED` or `VARIANCE_GRANTED`; when those hold, the application advances `SUBMITTED → APPROVED` and the system freezes the approved terms: `approved_type` and `approved_illumination` are set from the application, and `approved_area_sqft` is set to the smaller of `requested_area_sqft` and any granted AREA-variance value (falling back to `requested_area_sqft` when no AREA variance was granted). A denial advances `SUBMITTED → DENIED` unconditionally. Both `DENIED` and `PERMITTED` are terminal for an application.

### 3.3. Variances: Recommendation, Segregation of Duties, and the Revision Loop

When a proposed sign cannot meet a by-right standard, the applicant files a `Variance` against the application. The request names the `application_id`, the `kind` (`AREA`, `HEIGHT`, `SETBACK`, `HISTORIC`, or `ILLUMINATION`), a `requested_value` (the number the applicant asks to be allowed, such as a larger area — ignored for a `HISTORIC` request), and a `justification` describing the hardship. A new variance begins in `SUBMITTED`.

The variance moves through a two-step, deliberately separated approval. First a planner recommends, supplying a `recommendation` of `RECOMMEND_APPROVE` or `RECOMMEND_DENY`; this advances the variance `SUBMITTED → UNDER_REVIEW` and records both the `recommendation` and the `recommended_by_user_id`, set to the planner's `X-User-ID`. Then a member of the zoning board decides, supplying a `decision`. The board's decision is subject to **segregation of duties**: the deciding user's `X-User-ID`, captured as `decided_by_user_id`, must differ from the `recommended_by_user_id`; if they are equal the decision is refused with `ERR_SEGREGATION_OF_DUTIES`.

A `GRANT` decision advances `UNDER_REVIEW → GRANTED`, records `decided_by_user_id`, and sets `granted_value` — the value the board actually allows, which may be less than the applicant's `requested_value`. The effect of the grant depends on `kind`: a granted `AREA`, `HEIGHT`, or `SETBACK` variance makes relief available to the application's dimensional review (so a subsequent dimensional `PASS` tests against the granted figure), while a granted `HISTORIC` or `ILLUMINATION` variance additionally sets the application's `overlay_review` to `VARIANCE_GRANTED`. A `DENY` decision advances `UNDER_REVIEW → DENIED` and records `decided_by_user_id`. A `REVISE` decision advances `UNDER_REVIEW → REVISION_REQUESTED`, records `decided_by_user_id`, and returns the variance to the applicant's planner for re-recommendation — a re-recommend advances `REVISION_REQUESTED → UNDER_REVIEW` again, overwriting `recommendation` and `recommended_by_user_id`. This revision loop may cycle, but `GRANTED` and `DENIED` are terminal. All three board decisions — grant, deny, and revise — enforce the segregation-of-duties check.

Because a granted variance mutates the application (advancing its `version` and possibly its approved dimensions and fee), it is exactly the kind of drift the permit-issuance concurrency guard in Section 2.6 protects against.

### 3.4. Permit Issuance, Payment, Renewal, and Revocation

Once an application is `APPROVED`, a planner issues a `Permit` for it. The issuance request names the `application_id` and carries `expected_application_version` for the concurrency check described in Section 2.6; issuance against an application whose status is not `APPROVED` is refused with `ERR_APPLICATION_NOT_APPROVED`. On success the permit is created in `ISSUED` status with its `issued_at` stamped from the logical clock, the application transitions `APPROVED → PERMITTED`, and the application's `version` increments by one.

Issuance computes the **final permit fee**, `fee_charged_cents`, using the same tiered formula as the provisional estimate but evaluated over the approved terms rather than the requested ones. The fee is built from three parts. The **base** is chosen by sign type: 15000 cents for a `WALL` sign, 25000 cents for a `MONUMENT`, and 50000 cents for a `DIGITAL` sign. The **area component** charges only area beyond an included allowance of 32 square feet: let the billable area be the area in excess of 32 square feet (never below zero). The first 68 billable square feet — that is, area from 32 up to the tier-one cap of 100 square feet — are charged at 200 cents per square foot, and any area above 100 square feet is charged at 350 cents per square foot; the sum of these two pieces is rounded half up to whole cents to give the area fee. The **illumination surcharge** adds 0 cents for `NONE`, 5000 cents for `EXTERNAL`, and 20000 cents for `DIGITAL_DISPLAY`. The final fee is base plus area fee plus surcharge. The provisional fee computed at submission (`provisional_fee_cents`) uses this identical formula over the requested sign type, `requested_area_sqft`, and `requested_illumination`; the final fee uses `approved_type`, `approved_area_sqft`, and `approved_illumination`, so a partially granted AREA variance that reduced `approved_area_sqft` below the requested area makes the final charge diverge below the provisional estimate.

An applicant pays the permit, supplying `amount_cents`. Payment is legal only from `ISSUED`, and the amount must be at least `fee_charged_cents`, else `ERR_FEE_NOT_PAID`. Activation is further gated by the parcel's slot quota: if the parcel has no available sign slot (`available_sign_slots` would drop below zero), the payment is refused with `ERR_SIGN_SLOTS_EXHAUSTED`. On success the permit transitions `ISSUED → ACTIVE`, `fee_paid` is set true, `activated_at` is stamped from the clock, and `expires_at` is set to the activation instant plus the permit term of 365 days. Activating a permit consumes a slot: the parcel's `active_permit_count` increases by one and `available_sign_slots` decreases by one.

An applicant renews an `ACTIVE` or `EXPIRED` permit, provided `fee_paid` is already true and the current instant falls within the renewal window — no earlier than 30 days before `expires_at` and no later than 30 days after it — else `ERR_RENEWAL_WINDOW_CLOSED`. Renewal extends `expires_at` by another 365 days and increments the permit's `version`. When the permit being renewed had already lapsed to `EXPIRED`, the renewal also brings it back to `ACTIVE` and re-consumes a parcel slot (raising `active_permit_count` by one and lowering `available_sign_slots` by one); renewing a still-`ACTIVE` permit leaves the slot counters unchanged.

When the clock is advanced past an active permit's `expires_at`, the sweep transitions it `ACTIVE → EXPIRED` and releases its slot: `active_permit_count` drops by one and `available_sign_slots` rises by one.

A planner revokes a permit from either `ISSUED` or `ACTIVE`. Revocation sets `status` to `REVOKED`, refunds the fee by setting `fee_refunded_cents` equal to `fee_charged_cents` (restoring net permit revenue to its pre-issuance level), and, if the permit was `ACTIVE` at the time, releases its parcel slot. Revocation also cascades to inspections: every `SCHEDULED` inspection on the revoked permit is moved to `CANCELLED`. `REVOKED` is terminal.

### 3.5. Field Inspections

A planner schedules an `Inspection` on a permit, naming the `permit_id`, the `inspector_id`, and the window bounds `scheduled_start` and `scheduled_end`. The permit must be `ACTIVE`, else `ERR_PERMIT_INACTIVE`. Scheduling is protected against inspector double-booking: a new window may not fall within 60 minutes of another `SCHEDULED` inspection for the same inspector — the buffer applies on both sides of the existing window — else `ERR_INSPECTION_OVERLAP`. A new inspection begins in `SCHEDULED`.

The assigned inspector records the result, supplying an `outcome`. Recording is permitted only when the inspection's `inspector_id` equals the caller's `X-User-ID`. A recorded `PASS` moves the inspection `SCHEDULED → PASSED` and sets `outcome` to `PASS`; a recorded `FAIL` moves it `SCHEDULED → FAILED` and sets `outcome` to `FAIL`. An inspection may also reach `CANCELLED` without inspector action, as the cascade from a revoked or removal-ordered permit described in Sections 3.4 and 3.7. `PASSED`, `FAILED`, and `CANCELLED` are terminal.

### 3.6. The Non-Conforming Registry and Amortization

Signs that predate the current code but were lawful when built are recorded in the non-conforming registry. A planner registers one by naming the `parcel_id` where the grandfathered sign stands, a `description`, the assessed `original_value_cents` that serves as the amortization basis, and the `amortization_period_years` over which the sign must be written down. On registration the entry is `ACTIVE` and its `registered_at` is stamped from the logical clock, fixing the amortization basis date.

Each registration is reported with two live valuations, both recomputed at read time and during each clock sweep against the current clock. Let the elapsed time be the number of days between `registered_at` and the current instant, divided by 365 to yield elapsed years. The **straight-line** valuation, `straight_line_value_cents`, is `original_value_cents` multiplied by the remaining fraction of the term — one minus elapsed years divided by `amortization_period_years`, with that fraction floored at zero so the value never goes negative — then rounded half up to whole cents. The **declining-balance** valuation, `declining_balance_value_cents`, is `original_value_cents` multiplied by 0.8 (that is, one minus the decline rate of 0.20) raised to the power of the elapsed years, rounded half up to whole cents; because it decays geometrically it diverges from the straight-line figure for the same inputs. A registration's `status` becomes `AMORTIZED` once the elapsed years reach or exceed `amortization_period_years`.

### 3.7. Violations, Cure, Escalation, and Removal Orders

A planner cites a `Violation` against a parcel, naming the `parcel_id`, the `kind` (`NO_PERMIT`, `EXCEEDS_PERMIT`, `ILLEGAL_ILLUMINATION`, or `ABANDONED`), and optionally the implicated `permit_id` — which is left unset for an unpermitted-sign citation. A new violation is `OPEN`; its `issued_at` is stamped from the clock and its `cure_deadline` is set to the citation instant plus the cure period of 30 days.

From `OPEN`, a violation resolves one of two ways. A planner may mark it `CURED`, which is legal only on or before the `cure_deadline` — a cure attempt after the deadline is not permitted. Alternatively a planner may escalate it, but escalation is legal only strictly after the `cure_deadline` has passed; escalating on or before the deadline is refused with `ERR_CURE_PERIOD_ACTIVE`. Escalation advances the violation `OPEN → ESCALATED` and triggers a three-part cascade: first, a `RemovalOrder` is created in its sole `ISSUED` state, with `issued_at` equal to the escalation instant and a `compliance_deadline` set to that instant plus the removal-compliance period of 15 days, linked back through `violation_id`; second, if the violation carries a `permit_id`, that permit is driven to `REVOKED` (with the revocation's own refund and slot-release effects); and third, that revoked permit's `SCHEDULED` inspections are moved to `CANCELLED`. Both `CURED` and `ESCALATED` are terminal for a violation. A removal order is an append-only record — it carries only `id`, `created_at`, `violation_id`, `issued_at`, `compliance_deadline`, and its `status`, and it never leaves `ISSUED`.

### 3.8. Billboards: Registration, Renewal, and Exclusive Leasing

Freestanding billboard structures run on a parallel track. An operator creates a `Billboard`, naming the `parcel_id` it occupies, the `operator_id` (which must equal the caller's `X-User-ID`), the `face_count` of advertising faces, the `is_digital` flag, and the `structure_height_ft`. A new billboard is `UNREGISTERED`.

Registration and renewal share one action, driven by the current registration status. The operator supplies `amount_cents`, which must cover the computed registration fee, else `ERR_FEE_NOT_PAID`. The **registration fee** is metered per advertising face: the base per-face fee is 3333 cents, and for a digital structure each face's fee is that base multiplied by 1.5. Critically, the per-face fee is rounded half up **before** the faces are summed — so a digital face costs the rounded value of 3333 times 1.5 (that is, 5000 cents) and the total is that rounded per-face fee multiplied by `face_count`; a non-digital structure charges 3333 cents per face. Registering from `UNREGISTERED` or from `LAPSED` sets `registration_status` to `REGISTERED`, sets `registration_expires_at` to the current instant plus the registration term of 365 days, adds the computed fee to the cumulative `registration_fee_collected_cents`, and increments the billboard's `version`. Renewing while already `REGISTERED` is legal only when the current instant is no earlier than 30 days before `registration_expires_at`, else `ERR_RENEWAL_WINDOW_CLOSED`; a renewal extends `registration_expires_at` by another 365 days, again adds the fee to `registration_fee_collected_cents`, and increments the `version`. When the clock advances past `registration_expires_at`, the sweep moves the billboard `REGISTERED → LAPSED`, and every one of that billboard's `ACTIVE` leases cascades to `SUSPENDED`.

An advertiser's booking is captured as a `BillboardLease`. A lease names the `billboard_id`, the `lessee_name`, and the interval bounds `start_date` and `end_date`, and carries `expected_billboard_version` for the concurrency guard in Section 2.6. The billboard must be `REGISTERED`, else `ERR_BILLBOARD_NOT_REGISTERED`. The interval is half-open — the `start_date` is inclusive and the `end_date` is exclusive — and `end_date` must be strictly after `start_date`, else `ERR_INVALID_INTERVAL`. The structure is exclusive per interval: a new lease may not overlap any existing non-terminal lease on the same billboard, where overlap is judged on the half-open interval so two leases that merely abut (one ending exactly when the next begins) are allowed; an overlap is refused with `ERR_LEASE_OVERLAP`. A successful create places the lease in `ACTIVE` and increments the billboard's `version`. An operator may terminate an `ACTIVE` lease, moving it `ACTIVE → TERMINATED`. A lease also reaches `EXPIRED` when the clock sweeps past its `end_date`, or `SUSPENDED` when its parent billboard lapses; `TERMINATED` and `EXPIRED` are terminal.

## 4. Endpoint Definitions

All endpoints are mounted at the API root. Creation endpoints return HTTP 201 with the newly created resource; state transitions and other modifications return HTTP 200 with the updated resource; reads return HTTP 200. Error responses use the status codes catalogued in Section 5.

| Method | Path | Description | Authorized Role(s) |
|--------|------|-------------|--------------------|
| POST | `/_clock/set_current_utc` | Advance the logical clock and run time-based sweeps | Planner |
| POST | `/parcels` | Create a zoning parcel with its by-right standards | Planner |
| GET | `/parcels/{parcel_id}` | Read a parcel (includes live slot ledger) | Planner, Applicant, ZoningBoard, Inspector |
| POST | `/applicants` | Register an applicant/operator | Planner |
| POST | `/inspectors` | Register a field inspector | Planner |
| POST | `/applications` | Create a sign application (DRAFT) | Applicant |
| GET | `/applications/{application_id}` | Read an application | Planner, Applicant, ZoningBoard, Inspector |
| GET | `/applications` | List/filter applications | Planner, Applicant, ZoningBoard, Inspector |
| POST | `/applications/{application_id}/submit` | Submit a draft application; compute provisional fee | Applicant |
| POST | `/applications/{application_id}/review` | Record a dimensional or overlay review outcome | Planner |
| POST | `/applications/{application_id}/decide` | Approve or deny a reviewed application | Planner |
| POST | `/variances` | File a variance request against an application | Applicant |
| GET | `/variances/{variance_id}` | Read a variance | Planner, Applicant, ZoningBoard, Inspector |
| GET | `/variances` | List/filter variances | Planner, Applicant, ZoningBoard, Inspector |
| POST | `/variances/{variance_id}/recommend` | Recommend approve/deny on a variance | Planner |
| POST | `/variances/{variance_id}/decide` | Grant/deny/revise a variance (segregation of duties) | ZoningBoard |
| POST | `/permits` | Issue a permit for an approved application | Planner |
| GET | `/permits/{permit_id}` | Read a permit | Planner, Applicant, ZoningBoard, Inspector |
| GET | `/permits` | List/filter permits | Planner, Applicant, ZoningBoard, Inspector |
| POST | `/permits/{permit_id}/pay` | Pay a permit fee; consume a parcel slot | Applicant |
| POST | `/permits/{permit_id}/renew` | Renew an active/expired permit within its window | Applicant |
| POST | `/permits/{permit_id}/revoke` | Revoke a permit; refund and cancel inspections | Planner |
| POST | `/inspections` | Schedule an inspection on an active permit | Planner |
| GET | `/inspections/{inspection_id}` | Read an inspection | Planner, Applicant, ZoningBoard, Inspector |
| GET | `/inspections` | List/filter inspections | Planner, Applicant, ZoningBoard, Inspector |
| POST | `/inspections/{inspection_id}/record` | Record a PASS/FAIL outcome | Inspector |
| POST | `/non-conforming` | Register a non-conforming (grandfathered) sign | Planner |
| GET | `/non-conforming/{ncr_id}` | Read a registration with live valuations | Planner, Applicant, ZoningBoard, Inspector |
| GET | `/non-conforming` | List/filter registrations with live valuations | Planner, Applicant, ZoningBoard, Inspector |
| POST | `/violations` | Cite a code violation against a parcel | Planner |
| GET | `/violations/{violation_id}` | Read a violation | Planner, Applicant, ZoningBoard, Inspector |
| GET | `/violations` | List/filter violations | Planner, Applicant, ZoningBoard, Inspector |
| POST | `/violations/{violation_id}/cure` | Mark an open violation cured | Planner |
| POST | `/violations/{violation_id}/escalate` | Escalate an uncured violation; issue removal order | Planner |
| GET | `/removal-orders/{removal_order_id}` | Read a removal order | Planner, Applicant, ZoningBoard, Inspector |
| GET | `/removal-orders` | List/filter removal orders | Planner, Applicant, ZoningBoard, Inspector |
| POST | `/billboards` | Create a billboard structure (UNREGISTERED) | Applicant |
| GET | `/billboards/{billboard_id}` | Read a billboard | Planner, Applicant, ZoningBoard, Inspector |
| GET | `/billboards` | List/filter billboards | Planner, Applicant, ZoningBoard, Inspector |
| POST | `/billboards/{billboard_id}/register` | Register or renew a billboard's registration | Applicant |
| POST | `/billboard-leases` | Create an exclusive lease on a registered billboard | Applicant |
| GET | `/billboard-leases/{lease_id}` | Read a billboard lease | Planner, Applicant, ZoningBoard, Inspector |
| GET | `/billboard-leases` | List/filter billboard leases | Planner, Applicant, ZoningBoard, Inspector |
| POST | `/billboard-leases/{lease_id}/terminate` | Terminate an active lease | Applicant |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|----------|------------------|
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_APPLICATION_NOT_FOUND` | 404 |
| `ERR_PARCEL_NOT_FOUND` | 404 |
| `ERR_PERMIT_NOT_FOUND` | 404 |
| `ERR_BILLBOARD_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 422 |
| `ERR_INVALID_ENUM` | 422 |
| `ERR_INVALID_INTERVAL` | 422 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_APPLICATION_NOT_APPROVED` | 409 |
| `ERR_BILLBOARD_NOT_REGISTERED` | 409 |
| `ERR_PERMIT_INACTIVE` | 409 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_SIGN_AREA_EXCEEDED` | 409 |
| `ERR_SIGN_HEIGHT_EXCEEDED` | 409 |
| `ERR_SETBACK_INSUFFICIENT` | 409 |
| `ERR_ILLUMINATION_NOT_ALLOWED` | 409 |
| `ERR_HISTORIC_OVERLAY_REVIEW_REQUIRED` | 409 |
| `ERR_LEASE_OVERLAP` | 409 |
| `ERR_INSPECTION_OVERLAP` | 409 |
| `ERR_RENEWAL_WINDOW_CLOSED` | 409 |
| `ERR_CURE_PERIOD_ACTIVE` | 409 |
| `ERR_FEE_NOT_PAID` | 402 |
| `ERR_SIGN_SLOTS_EXHAUSTED` | 409 |
| `ERR_STALE_VERSION` | 412 |
