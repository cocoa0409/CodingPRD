# Campus & Community Basic Needs Hub API — Product Requirements Document

## 1. Introduction

The Campus & Community Basic Needs Hub is the operational backbone of a college basic-needs center serving enrolled students, community residents, and faculty or staff who face food insecurity, housing instability, or sudden financial emergencies. The hub consolidates services that are otherwise fragmented across campus and community offices: a confidential eligibility intake, a points-based food and essentials pantry, benefits screening with application assistance for SNAP, childcare, and housing programs, an emergency grant fund with rapid disbursement, short-term shelter coordination, a partner-agency referral network with warm handoffs, and outreach programming designed to reduce the stigma that keeps eligible clients from asking for help. Every design decision in this API subordinates operational convenience to two commitments: client confidentiality — clients are known by self-chosen aliases, and intake data is walled off from operational roles — and dignified, low-friction access — including anonymous self-registration and anonymous browsing of outreach events.

This document specifies the hub's REST API for the engineering team building it. Eligibility across services is anchored to a single verified intake assessment per client, from which the system derives risk tiering, pantry budgets, and screening scores. Monetary programs are governed by conservative fund accounting, segregation of duties between application creation, review, and disbursement, and hard award caps. Time-dependent obligations — referral acknowledgement deadlines, grant disbursement windows, assessment validity periods, shelter arrival grace, and event completion — are all evaluated against a controllable logical clock rather than the wall clock, so that scheduled transitions are deterministic and testable. The sections below define the system-wide contract first, then the business workflows in which those rules live, then the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring their operational capacity. The system recognizes nine roles, spelled exactly as follows: `Anonymous`, `Client`, `IntakeCoordinator`, `PantryStaff`, `BenefitsCounselor`, `GrantReviewer`, `ShelterCoordinator`, `HubAdmin`, and `PartnerAgencyRep`.

Identity resolution differs by role, and it is part of the authentication contract:

- When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting Client record. The referenced client must exist and must not be `EXITED`. Ownership checks on any resource that references a client compare the resource's owning `client_id` to `X-User-ID`; a `Client`-role caller touching another client's resource is rejected with `ERR_FORBIDDEN_OWNERSHIP`.
- When `X-User-Role` is one of the five staff-backed roles — `IntakeCoordinator`, `PantryStaff`, `BenefitsCounselor`, `GrantReviewer`, or `ShelterCoordinator` — `X-User-ID` is the `id` of the acting StaffMember. The referenced staff member must exist, must be `ACTIVE`, and its `staff_role` must match the claimed role: `INTAKE_COORDINATOR` for `IntakeCoordinator`, `PANTRY_STAFF` for `PantryStaff`, `BENEFITS_COUNSELOR` for `BenefitsCounselor`, `GRANT_REVIEWER` for `GrantReviewer`, and `SHELTER_COORDINATOR` for `ShelterCoordinator`. Ownership checks on staff-pinned actions compare the recorded actor field (for example, a screening's `counselor_id` or a grant application's `reviewed_by`) to `X-User-ID`.
- When `X-User-Role` is `PartnerAgencyRep`, `X-User-ID` is the `id` of the PartnerAgency the representative acts for; the referenced agency must exist. Agency-scoped checks compare the referral's `agency_id` to `X-User-ID`.
- When `X-User-Role` is `HubAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. It is never resolved against a StaffMember row at authentication time, although the grant two-person rule compares it against the recorded `reviewed_by` of the application being disbursed.
- When `X-User-Role` is `Anonymous`, the caller is an unauthenticated visitor; `X-User-ID` may be omitted, and when present it is an opaque identifier not tied to any persisted entity. Anonymous access exists for stigma reduction: self-registration and public browsing of the outreach event list only.

A request with a missing or unknown `X-User-Role`, a missing `X-User-ID` where the role requires one, or an entity-backed identity that fails to resolve (no such client, staff member, or agency; an `INACTIVE` staff member; an `EXITED` client; or a `staff_role` that contradicts the claimed role) is rejected with `ERR_UNAUTHENTICATED`. Once authenticated, a caller whose role does not appear in the endpoint's authorized role list is rejected with `ERR_FORBIDDEN_ROLE`. Scope violations after successful authentication — a client touching another client's record, a representative touching another agency's referral, or a staff-pinned action attempted by anyone other than the recorded actor — are rejected with `ERR_FORBIDDEN_OWNERSHIP`.

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

List endpoints paginate through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order. List responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and the Sweep Checkpoint

Every date-window rule in the hub — the rolling pantry visit window, weekly points windows, referral acknowledgement deadlines, assessment validity, grant disbursement windows, shelter arrival grace, and event dates — evaluates against a server-held **logical clock**, never the wall clock. Before any call has been made, the logical clock reads exactly `2026-08-01T00:00:00Z`; this fixed startup default never falls back to wall-clock time.

Two admin-only test-driving capabilities govern time. The first advances the logical clock to a supplied `to_iso8601` instant and replies with the new `current_utc`. The clock moves forward only. Advancing the clock does not by itself fire any automatic transition; time-driven transitions are evaluated only when the second capability, the **sweep checkpoint**, is invoked. A single sweep evaluates every pending clock-driven transition in a pinned order: first, verified assessments whose validity has lapsed flip from `VERIFIED` to `EXPIRED`; second, `SENT` referrals past their acknowledgement deadline flip to `EXPIRED`; third, `RESERVED` shelter stays past their arrival grace flip to `NO_SHOW`; fourth, `APPROVED` grant applications past their disbursement window flip to `EXPIRED`; fifth, `OPEN` or `FULL` outreach events a full day past their start flip to `COMPLETED`. Each transition that fires runs all of its documented side effects, including fund reopens and the promotion of queued grant applications. The sweep response reports per-type tallies: `assessments_expired`, `referrals_expired`, `stays_marked_no_show`, `grants_expired`, `events_completed`, and `queued_grants_promoted`.

### 2.5. Common Resource Properties

Every primary resource carries a standard set of system-managed fields:

- `id` — a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` — an integer that starts low and increments by one on every mutation, including mutations caused only by derived-field reconciliation.

One exception exists by design: a visit line item is an immutable-by-construction sub-record and carries only `id` and `created_at`; it has neither `updated_at` nor `version`. Any recalculation of a derived field on a resource — a client's points totals, an item's restock flag, a fund's counters, an event's registration counts — is itself a mutation of that resource and therefore refreshes its `updated_at` and increments its `version`.

### 2.6. Request Validation Cascade and Nested Resource Retrieval

Every request is evaluated against a fixed cascade of checks, and a rejection at any step halts the cascade — earlier failures mask later ones rather than accumulating. The ordering is:

1. **Authentication** — header presence and identity resolution per §2.1; failures yield `ERR_UNAUTHENTICATED`.
2. **Role authorization** — the claimed role must appear in the endpoint's role list; failures yield `ERR_FORBIDDEN_ROLE`.
3. **Path existence** — resources referenced in the URL are validated strictly left to right: the client first, then the child resource, then deeper segments. The first identifier that does not resolve yields `ERR_NOT_FOUND`, and no later segment is examined. A request targeting an assessment under a non-existent client therefore fails on the client before the assessment is ever considered.
4. **Ownership and scope** — client self-scope, agency self-scope, and actor-pinned checks per §2.1; failures yield `ERR_FORBIDDEN_OWNERSHIP`.
5. **Confidentiality wall** — the confidential-collection gate of §2.9; failures yield `ERR_CONFIDENTIAL`.
6. **State admission** — the target resource's current state must admit the requested transition. Where the governing state machine names a machine-specific error, that error applies; otherwise the generic fallback is `ERR_INVALID_STATE`.
7. **Optimistic concurrency** — on endpoints that take an expected-version field, the check of §2.8 runs immediately after state preconditions and before any business rule; failures yield `ERR_STALE_VERSION`.
8. **Client-status gate** — operations that require an `ACTIVE` client; failures yield `ERR_CLIENT_NOT_ACTIVE`.
9. **Verified-assessment gate** — operations that size benefits off household data; failures yield `ERR_ASSESSMENT_REQUIRED`.
10. **Domain business rules** — segregation of duties, consent, temporal windows, frequency limits, placement and overlap constraints, uniqueness, referential checks, capacity admission, fiscal checks, fund-lifecycle gates, and eligibility gates, each detailed in §3 beside the workflow it guards.

Two illustrations make the ordering concrete. A grant approval attempted by a reviewer other than the recorded `reviewed_by` is rejected with `ERR_FORBIDDEN_OWNERSHIP` even when the application is also in a non-reviewable state, because ownership precedes state admission. And a stale `expected_fund_version` surfaces as `ERR_STALE_VERSION` only after the application's state admission has passed and before any award sizing runs.

### 2.7. Money, Points, and Numeric Precision

All monetary amounts are represented as integer cents; there are no fractional-cent values anywhere in the API. Derived monetary figures are whole cents. Percentage-based derivations that must land on whole cents pin their rounding per step: the SNAP estimate rounds its earned deduction half-up to a whole cent, floors the half-of-adjusted-income divisor to a whole cent, and rounds the thirty-percent household share up to a whole cent, in that pinned order — computing unrounded intermediates and rounding only at the end is not permitted, because it yields different cents. The intake `income_ratio` is a ratio rounded half-up to exactly four decimal places, and eligibility-band comparisons against it are inclusive of the band boundaries. Screening scores are integers rounded half-up and clamped to the range 0 through 100. Pantry points are integers; weekly-window membership is inclusive — a visit whose `week_start` equals the current window's `week_start` counts. Shelter arithmetic works in whole ISO calendar days, and referral capacity scaling rounds the multiplied capacity down to a whole number before comparison. Grant requests are bounded: the `requested_cents` of an application must be at least 100 cents and at most 150,000 cents (the per-award cap), and a separate lifetime ceiling of 300,000 cents per client applies across all funds and all time.

### 2.8. Optimistic Concurrency Control

Three write operations require the caller to prove it has observed the current state of a parent entity before writing. Each takes a non-optional expected-version field, and a mismatch between the supplied value and the parent entity's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not listed here take no version field.

- **Assessment verification** requires `expected_client_version` carrying the client's current `version`. A successful verification legitimately supersedes the client's prior verified assessment and advances the client's `version` by one, so a verification carrying an older expected version is operating on a client snapshot the caller has not re-read and is rejected with `ERR_STALE_VERSION` (HTTP 412).
- **Pantry-item configuration updates** require `expected_item_version` carrying the item's current `version`. Restocks, checkouts, and void-restores legitimately advance the item's `version` between the caller's read and the write; a configuration update carrying a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412).
- **Grant approval** requires `expected_fund_version` carrying the fund's current `version`. Any approval, disbursement, or approval expiry on the same fund legitimately moves `committed_cents` and advances the fund's `version`, so an approval carrying a stale value would size an award off a remaining-basis snapshot the caller no longer holds and is rejected with `ERR_STALE_VERSION` (HTTP 412).

### 2.9. Confidentiality Walls and Segregation of Duties

Clients are known to the hub by `alias_name`, a confidential pseudonym chosen by the client — never a legal name. The two confidential data families are intake assessments and benefits screenings. `PantryStaff`, `ShelterCoordinator`, and `PartnerAgencyRep` callers never read either family: any attempt by one of those roles to read assessment or screening data, whether listing the collections or reading a single record, is rejected with `ERR_CONFIDENTIAL`. The remaining roles read them within their ordinary scopes (`Client` restricted to its own records).

Grant handling enforces segregation of duties at two joints. First, the reviewer who begins review of an application must not be the user recorded as its `created_by_user_id`; because grant creation is open to `GrantReviewer` for staff-assisted intake, this conflict is reachable and is rejected with `ERR_SOD_CONFLICT`. Second, the two-person rule on disbursement requires the disbursing `HubAdmin`'s `X-User-ID` to differ from the application's recorded `reviewed_by`; a violation is likewise `ERR_SOD_CONFLICT`. Neither rule can be waived.

### 2.10. Derived Fields and Automatic Posture Changes

A large share of the hub's state is system-maintained and recomputed as events occur rather than accepted from callers: the client's risk tier, effective household size, points allotment and spent totals, lifetime grant total, no-show count, and shelter restriction; the pantry item's `restock_flag`; the fund's committed and disbursed counters and both remaining bases; the agency's `active_referral_count`; the event's `registered_count` and `attended_count`; and the counselor's `active_case_load`. These recomputations follow the workflows that trigger them in §3 and are mutations in the sense of §2.5.

Several postures flip automatically when their criteria are met, without an explicit call on the resource itself. A client in `INTAKE_PENDING` flips to `ACTIVE` when the client's first assessment is verified. A fund flips from `OPEN` to `EXHAUSTED` when an approval consumes the last of its committed-basis remainder, and back to `OPEN` when disbursement or approval expiry restores headroom — each reopen promoting one queued application. An outreach event flips from `OPEN` to `FULL` when registrations reach capacity and back to `OPEN` when a cancellation opens a seat. A client becomes shelter-restricted when repeat no-shows cross the policy threshold. Each such flip is an atomic consequence of the triggering event and carries the cascade described with that event.

## 3. Business Logic & Workflows

### 3.1. Staffing the Hub and Registering Clients

Before any staff-backed role can act, a `HubAdmin` bootstraps the staff directory by registering each StaffMember with a `full_name`, an `email`, and a `staff_role` of `INTAKE_COORDINATOR`, `PANTRY_STAFF`, `BENEFITS_COUNSELOR`, `GRANT_REVIEWER`, or `SHELTER_COORDINATOR`. The `email` must be unique across the directory; a duplicate is rejected with `ERR_DUPLICATE_STAFF_EMAIL`. New staff members start `ACTIVE` with an `active_case_load` of zero, and the directory can be listed with optional `staff_role` and `status` filters.

Client registration is deliberately low-barrier: a visitor may self-register as `Anonymous`, or an `IntakeCoordinator` or `HubAdmin` may register a client on their behalf. Registration captures the client's `alias_name`, a `contact_channel` of `EMAIL`, `SMS`, `PHONE`, or `NONE`, and a `population_type` of `ENROLLED_STUDENT`, `COMMUNITY_RESIDENT`, or `FACULTY_STAFF`. The optional `enrolled_credits` defaults to 0 and may legitimately be 0, except that an `ENROLLED_STUDENT` must carry at least 6 credits this term; fewer is rejected with `ERR_INVALID_REQUEST`. A newly registered client is `INTAKE_PENDING` and remains so until a first assessment is verified, with `risk_tier` null until that first verification. The client roster can be listed by staff with optional `status`, `population_type`, and `risk_tier` filters; a `Client`-role caller reads only its own record.

A client's standing is managed through three administrative actions. Suspension by a `HubAdmin` moves an `ACTIVE` client to `SUSPENDED` — a client in any other state is rejected with `ERR_CLIENT_NOT_ACTIVE` — and as a protective side effect the client's open pantry visit, if one is checked in at that moment, is auto-voided: its provisional lines are discarded and its frequency slot is freed. Reinstatement by a `HubAdmin` moves a `SUSPENDED` client back to `ACTIVE`. Exiting, available to an `IntakeCoordinator` or `HubAdmin` from either `ACTIVE` or `SUSPENDED` (otherwise `ERR_CLIENT_NOT_ACTIVE`), moves the client to the terminal `EXITED` state and unwinds every open engagement in one atomic event: all future shelter stays still `RESERVED` are cancelled, freeing their bed intervals; all referrals in `INITIATED` or `SENT` are withdrawn, and withdrawing a `SENT` referral decrements the receiving agency's `active_referral_count`; every registration still `REGISTERED` for an event whose `event_date` lies in the future is cancelled, each cancellation recomputing its event's `registered_count` and possibly flipping the event from `FULL` back to `OPEN`; the client's checked-in pantry visit, if any, is voided; and any of the client's assessments still in `DRAFT` are moved to `DISCARDED`.

### 3.2. The Confidential Intake: Assessment Lifecycle

The IntakeAssessment is the hub's eligibility foundation. A `Client` may draft one for itself, or an `IntakeCoordinator` may draft one on the client's behalf, for any client who is not `EXITED` (drafting for an exited client fails with `ERR_CLIENT_NOT_ACTIVE`). The draft captures: `household_size`, the number of people in the household including the client, at least 1; `monthly_income_cents`, gross monthly household income in cents, at least 0; `earned_income_cents`, the wage portion of that income, defaulting to 0 and bounded between 0 and `monthly_income_cents`; `shelter_cost_cents`, monthly rent, mortgage, and utility costs, defaulting to 0; `housing_status` of `STABLE`, `COST_BURDENED`, `UNSTABLE`, or `HOMELESS`; `dependents_under_18`, at least 0 and strictly fewer than `household_size`; `receives_snap` and `receives_childcare_subsidy` flags; `food_insecurity_score`, the USDA six-item screener raw score from 0 to 6; and `consent_confidential`, the client's informed consent to confidential handling. A new assessment is `DRAFT`. Assessments are confidential per §2.9; the collection supports `client_id`, `status`, and `verified_by` filters.

Submitting moves an assessment from `DRAFT` to `SUBMITTED` — a submit from any other state is rejected with `ERR_ASSESSMENT_NOT_EDITABLE`. Submission requires `consent_confidential` to be true, else `ERR_CONSENT_REQUIRED`, and re-validates the numeric domains above — household size at least 1, non-negative income, the earned portion within total income, dependents fewer than the household size, and the food score within 0 to 6 — with violations rejected as `ERR_INVALID_REQUEST`. Two things freeze at submit time. The `submitted_at` timestamp — null until this moment — records the logical time of submission. And the assessment's `income_ratio` and `eligibility_band` are computed and frozen on the record: the ratio divides `monthly_income_cents` by the applicable poverty baseline and is rounded half-up to four decimal places. The baseline is 125,500 cents monthly for a household of one, 169,300 for two, 213,100 for three, 256,900 for four, 300,700 for five, 344,500 for six, 388,300 for seven, and 432,100 for eight; households larger than eight use the eight-person baseline plus 43,800 cents for each additional person beyond eight. A household whose `housing_status` is `HOMELESS` is banded `FULL` unconditionally, regardless of ratio. Otherwise a ratio of at most 1.30 bands `FULL`, a ratio above 1.30 but at most 2.00 bands `PARTIAL`, and anything above 2.00 bands `INELIGIBLE`.

Verification is the pivotal coordinator act and moves an assessment from `SUBMITTED` to `VERIFIED`. Only an `IntakeCoordinator` may verify, the assessment must be `SUBMITTED` (else `ERR_ASSESSMENT_NOT_EDITABLE`), the client must be `INTAKE_PENDING` or `ACTIVE` (else `ERR_CLIENT_NOT_ACTIVE`), and the request must carry `expected_client_version` per §2.8. A successful verification stamps `verified_at` with the logical now, records the acting coordinator's staff id in `verified_by`, and sets `expires_at` exactly 365 days after verification — all three fields null until this moment — the expiry boundary is exclusive in the sense that the assessment expires as soon as the logical clock reaches or passes `expires_at`. Any other `VERIFIED` assessment of the same client is automatically superseded to `SUPERSEDED`, so at most one verified assessment exists per client at any time. The client's derived fields are then recomputed from the newly verified assessment: `household_size_effective` takes the assessment's `household_size`, the `pantry_points_allotment` is recomputed per the weekly-budget rule, and `risk_tier` is recomputed per the tier rule — both described below. When the verified assessment is the client's first, the client flips automatically from `INTAKE_PENDING` to `ACTIVE`. Each verification also increments the client's `version` by one, which is precisely what makes a second verification carrying the older `expected_client_version` stale.

The tier rule reads the client's single verified assessment, null-safe: with no verified assessment the client's `risk_tier` is null. A household that is `UNSTABLE` or `HOMELESS`, or whose `food_insecurity_score` is at least 5, tiers `CRISIS`. Failing that, a `COST_BURDENED` household, a food score of at least 3, or an `income_ratio` of at most 1.30 tiers `ELEVATED`. Everything else tiers `STABLE`.

The points-budget rule derives the client's `pantry_points_allotment` for the current week window: a base of 30 points, plus 10 points for each household member beyond the first (per `household_size_effective`), capped at 60 points. When the client has no verified assessment, `household_size_effective` is null and the allotment is 0. The window key is `pantry_week_start`, the Monday at 00:00:00.000Z of the current logical week.

Two corrective paths round out the lifecycle. Returning, by an `IntakeCoordinator`, moves a `SUBMITTED` assessment to `RETURNED` and records the coordinator's `return_notes` — a field that stays null unless the assessment is returned. Revising, by the client or an `IntakeCoordinator`, reopens a `RETURNED` assessment to `DRAFT`; any of the draft's payload fields supplied with the revision overwrite the corresponding fields in place, and the previously frozen `income_ratio` and `eligibility_band` are cleared until the next submit. Finally, the sweep expires a `VERIFIED` assessment once the logical clock reaches its `expires_at`; when no other verified assessment remains for the client, the client's derived fields unwind — `household_size_effective` returns to null, `pantry_points_allotment` to 0, and `risk_tier` to null.

Two further client-level derived figures accumulate over time and appear on the client record. `lifetime_grant_cents` sums the `approved_cents` of the client's `DISBURSED` emergency grant applications across all funds and all time. `shelter_no_show_count_90d` counts the client's shelter stays flipped to `NO_SHOW` whose `no_show_marked_at` falls within the trailing 2,160 hours (90 days) of the logical now; when that count reaches 2, the client's `shelter_restricted` flag becomes true and blocks new stay creation per §3.6.

### 3.3. The Pantry: Catalog, Visit Frequency, and the Weekly Points Economy

The pantry catalog is administered by a `HubAdmin`. Creating a PantryItem takes an `item_name`, a `category` of `PERISHABLE`, `SHELF_STABLE`, `HYGIENE`, or `BABY_CARE`, a `point_cost` of at least 1 point per unit, an initial `quantity_on_hand`, a `reorder_threshold` of at least 0, and a `per_visit_limit` of at least 1. The `item_name` must be unique among items that are not discontinued — a name colliding with an `ACTIVE` item is rejected with `ERR_DUPLICATE_ITEM`, while a name retired with a discontinued item may be reused. The item starts `ACTIVE`, and its `restock_flag` is initialized immediately: true when the initial stock is at or below the reorder threshold. The catalog is browsable by clients and every staff role, with optional `category` and `status` filters.

Three maintenance operations keep the catalog current. A configuration update by a `HubAdmin` may change `point_cost`, `reorder_threshold`, or `per_visit_limit` and must carry `expected_item_version` per §2.8; it advances the item's `version` by one, and a `point_cost` change never retro-edits the pinned `points_charged` of line items already recorded. A restock by `PantryStaff` or a `HubAdmin` takes a `quantity` of at least 1, adds it to `quantity_on_hand`, recomputes `restock_flag`, and advances the item's `version` by one. Discontinuation by a `HubAdmin` moves an `ACTIVE` item to `DISCONTINUED` (any other state is `ERR_INVALID_STATE`); a discontinued item is excluded from new line-item adds — attempted adds fail with `ERR_ITEM_NOT_AVAILABLE` — while lines already sitting in a checked-in visit remain chargeable at checkout.

A pantry visit begins when `PantryStaff` checks a client in. Check-in requires the client to be `ACTIVE` (else `ERR_CLIENT_NOT_ACTIVE`) and to hold a verified assessment (else `ERR_ASSESSMENT_REQUIRED`). Two frequency rules then apply, in cascade order. The rolling-window rule counts the client's visits in `CHECKED_IN` or `COMPLETED` status whose `visit_date` falls strictly inside the trailing 168 hours — a visit exactly 168 hours old does not count, and `VOIDED` visits never count — and rejects the check-in with `ERR_VISIT_LIMIT_EXCEEDED` when that count has already reached 2; the second visit inside the window is admitted, the third rejected. The one-open-visit rule rejects a check-in with `ERR_VISIT_ALREADY_OPEN` when the client already has a `CHECKED_IN` visit. A new visit starts `CHECKED_IN` with `visit_date` set to the logical now, `week_start` set to the Monday 00:00:00.000Z of the containing logical week — that `week_start` is the aggregation key for the weekly points economy — and `points_spent` held at 0 while the visit is open. Visits are listable with optional `client_id` and `status` filters; a `Client`-role caller sees only its own visits.

While a visit is open, `PantryStaff` adds line items to it — one line per item take — supplying the `item_id` and a `quantity` of at least 1. Line adds are admitted only on a `CHECKED_IN` visit (else `ERR_VISIT_NOT_OPEN`); the referenced item must be `ACTIVE` with `quantity_on_hand` covering the requested quantity (else `ERR_ITEM_NOT_AVAILABLE`); and the cumulative units of that item across the visit — including earlier lines — must not exceed the item's `per_visit_limit` (else `ERR_ITEM_LIMIT_EXCEEDED`). Each recorded line pins its `points_charged` as the line's `quantity` multiplied by the item's `point_cost` at that moment, and the visit's `provisional_points` grows by the same amount. A line item carries its `visit_id`, `item_id`, `quantity`, and pinned `points_charged`; per §2.5 it carries only `id` and `created_at` as common fields. Line items are listable by `PantryStaff` and `HubAdmin` with optional `visit_id` and `item_id` filters.

Checkout by `PantryStaff` settles the visit and runs its checks in order: the visit must be `CHECKED_IN` (else `ERR_VISIT_NOT_OPEN`); it must hold at least one line item (else `ERR_EMPTY_CHECKOUT`); every line's item must still have `quantity_on_hand` covering the pinned line quantity (else `ERR_ITEM_NOT_AVAILABLE`); and the reserved-basis points test must pass — the client's `pantry_points_spent_settled` for the current week window plus this visit's `provisional_points` must not exceed the client's `pantry_points_allotment`, where exactly reaching the allotment passes and any excess is rejected with `ERR_POINTS_BALANCE_EXCEEDED`; finally the client must still be `ACTIVE` (else `ERR_CLIENT_NOT_ACTIVE`). On success the visit moves to `COMPLETED`: `points_spent` is finalized to the provisional total and `provisional_points` is cleared to 0; each line decrements its item's `quantity_on_hand` by the line quantity, and every such decrement recomputes that item's `restock_flag`, setting it when stock falls to or below the reorder threshold; and the client's spent totals are recomputed.

The two spent figures on the client record differ deliberately. `pantry_points_spent_settled` sums `points_spent` over the client's `COMPLETED` visits whose `week_start` equals the current window — an open checked-in visit does not reduce the displayed settled figure. `pantry_points_spent_reserved` adds the open visit's `provisional_points` on top of the settled figure — identical data therefore yields a larger reserved figure while a visit is open, and the reserved basis is what checkout admission enforces.

Voiding, by `PantryStaff` or a `HubAdmin`, or by the system itself on client suspension or exit, reverses a visit from either non-terminal state (a void from a terminal state is `ERR_VISIT_NOT_OPEN`). Voiding a `CHECKED_IN` visit discards its provisional lines with no stock or points movement and frees its frequency slot. Voiding a `COMPLETED` visit restores each line's `quantity_on_hand` by the line quantity — each restore recomputing the item's `restock_flag`, clearing it when stock climbs back above the reorder threshold — recomputes the client's settled points downward, resets the visit's `points_spent` to 0, and frees the frequency slot, since `VOIDED` visits do not count toward the rolling 168-hour limit.

### 3.4. Benefits Screening and Counselor Caseloads

A benefits screening opens when an `IntakeCoordinator` or `BenefitsCounselor` creates one for a client, supplying the `program` — `SNAP`, `CHILDCARE`, or `HOUSING`. The client must be `ACTIVE` (else `ERR_CLIENT_NOT_ACTIVE`) and hold a verified assessment (else `ERR_ASSESSMENT_REQUIRED`). The hub assigns the counselor itself: the candidate pool is all `ACTIVE` staff members whose `staff_role` is `BENEFITS_COUNSELOR`, and an empty pool rejects the creation with `ERR_NO_COUNSELOR_AVAILABLE`. Among candidates, the one with the lowest `active_case_load` is chosen, ties broken by the earliest `created_at`; the selection is a deterministic total order with no random tie-breaking. The chosen counselor's id lands in the screening's `counselor_id`, and assignment immediately increments that counselor's `active_case_load`, which counts the counselor's screenings in `STARTED`, `SCREENED`, `APPLICATION_ASSISTED`, or `SUBMITTED` status. A new screening is `STARTED`, with `score`, `result_band`, and `snap_estimate_cents` null until scoring, and `determination_outcome` and `determined_at` null until a determination is recorded. Screenings are confidential per §2.9; the collection supports `client_id`, `counselor_id`, `program`, and `status` filters.

Scoring is performed by the assigned counselor and moves the screening from `STARTED` to `SCREENED`. The screening must be `STARTED` (else `ERR_SCREENING_NOT_ACTIONABLE`), the acting counselor must equal `counselor_id` (else `ERR_FORBIDDEN_OWNERSHIP`), and the client must hold a verified assessment (else `ERR_ASSESSMENT_REQUIRED`). Scoring computes three component figures from the verified assessment. Income points run 100 times one minus half the assessment's `income_ratio`, floored at 0 — a linear decay that reaches zero at a ratio of 2.0. Food points run 100 times the `food_insecurity_score` divided by 6. Housing points map the `housing_status`: 0 for `STABLE`, 60 for `COST_BURDENED`, 85 for `UNSTABLE`, 100 for `HOMELESS`. The raw score is the weighted blend, rounded half-up to an integer and clamped between 0 and 100, with per-program weights: `SNAP` weighs income 0.6, food 0.3, housing 0.1; `CHILDCARE` weighs income 0.5, food 0.1, housing 0.4; `HOUSING` weighs income 0.4, food 0.1, housing 0.5. Three gates override the blend: a `CHILDCARE` screening for a household with zero `dependents_under_18` scores 0 outright; a `SNAP` screening for a client whose `receives_snap` is already true scores 0 — there is nothing to screen; and a `HOUSING` screening for a `STABLE` household is capped at the smaller of 39 and the raw score. The resulting `score` lands in one of three bands with inclusive boundaries: 70 or higher is `LIKELY_ELIGIBLE`, 40 through 69 is `POSSIBLY_ELIGIBLE`, and below 40 is `NOT_ELIGIBLE`; the band is recorded as `result_band`.

For `SNAP` screenings, scoring additionally computes `snap_estimate_cents`, the estimated monthly benefit, from the verified assessment in seven pinned steps. Step one deducts twenty percent of `earned_income_cents`, rounded half-up to a whole cent. Step two subtracts that earned deduction and the 19,800-cent standard deduction from `monthly_income_cents`, floored at zero, yielding adjusted income. Step three takes `shelter_cost_cents` minus half of adjusted income — the halving rounded down to a whole cent — floored at zero, yielding excess shelter. Step four caps excess shelter at the 67,200-cent shelter cap. Step five subtracts the capped shelter from adjusted income, floored at zero, yielding net income. Step six takes thirty percent of net income, rounded up to a whole cent, as the household's expected share. Step seven subtracts that share from the maximum monthly allotment for the household size — 29,200 cents for one person, 53,600 for two, 76,800 for three, 97,500 for four, 115,800 for five, 139,000 for six, 153,600 for seven, 175,600 for eight, with households larger than eight using the eight-person figure — floored at zero. Each step rounds before the next step reads it; computing with unrounded intermediates and rounding only at the end is a different, non-conforming calculation.

Assistance and reporting proceed only through the assigned counselor (any other counselor is `ERR_FORBIDDEN_OWNERSHIP`). Recording application assistance moves `SCREENED` to `APPLICATION_ASSISTED` and requires a `result_band` of `LIKELY_ELIGIBLE` or `POSSIBLY_ELIGIBLE` — assisting a `NOT_ELIGIBLE` screening, or assisting from any other state, is `ERR_SCREENING_NOT_ACTIONABLE`. Marking the assisted application as submitted to the agency moves `APPLICATION_ASSISTED` to `SUBMITTED`. Recording the agency's determination moves `SUBMITTED` to `DETERMINED`: the call carries an `outcome` of `APPROVED_BY_AGENCY` or `DENIED_BY_AGENCY` (any other value is `ERR_INVALID_REQUEST`), which is recorded as `determination_outcome` alongside the `determined_at` timestamp, and determinations feed the usage summary's conversion metrics. Withdrawing is available from any pre-terminal state — `STARTED`, `SCREENED`, `APPLICATION_ASSISTED`, or `SUBMITTED` — and moves the screening to `WITHDRAWN`; from anywhere else it is `ERR_SCREENING_NOT_ACTIONABLE`.

### 3.5. Emergency Grants: Fund Accounting, Review, and Rapid Disbursement

Emergency aid is drawn from fiscal-year grant funds administered by a `HubAdmin`. Creating a GrantFund takes a `fund_name`, a `fiscal_year` label such as 2026, and an `allocated_cents` pool strictly greater than zero; the pair of `fund_name` and `fiscal_year` must be unique, with duplicates rejected as `ERR_DUPLICATE_FUND`. A new fund is `OPEN` with its counters zeroed. Fund reads — available to `GrantReviewer` and `HubAdmin` — expose four maintained figures. `committed_cents` sums the `approved_cents` of the fund's applications currently in `APPROVED`. `disbursed_cents` sums them over `DISBURSED`. Two remainder readings derive from those: `remaining_committed_basis` is the allocation minus committed minus disbursed — the conservative reading, in which committed money is spoken for, and the only reading award sizing and exhaustion posture trust; `remaining_cash_basis` is the allocation minus disbursed alone — the optimistic reading reported for cash planning. On a 500,000-cent fund with 100,000 committed and 50,000 disbursed, the committed basis reads 350,000 while the cash basis reads 450,000, diverging by exactly the committed amount.

An application is drafted under a client by the client personally, by an `IntakeCoordinator`, or by a `GrantReviewer` assisting intake. The draft names the `fund_id` it draws on, a `category` of `RENT`, `UTILITY`, `FOOD`, `MEDICAL`, `TRANSPORT`, or `CHILDCARE`, a `requested_cents` between 100 and 150,000 cents inclusive (outside that range is `ERR_INVALID_REQUEST`), and a free-text `hardship_statement`. The creator's `X-User-ID` is stamped into `created_by_user_id` — the client's own id for self-service or the assisting staff member's id — and this stamp drives segregation of duties per §2.9: a `GrantReviewer` who assisted the intake is thereafter barred from reviewing that application. The target fund must not be `CLOSED` (else `ERR_FUND_CLOSED`). A new application is `DRAFT`: `approved_cents` sits at 0 and `approved_at` stays null until an approval, `disbursed_at` stays null until a disbursement, `reviewed_by` stays null until a reviewer claims the application, and `info_request_notes` and `decision_rationale` stay null unless those respective events occur. The collection supports `client_id`, `fund_id`, `reviewed_by`, and `status` filters; a `Client`-role caller sees only its own applications.

Submission, by the creating client or an `IntakeCoordinator`, requires the client `ACTIVE` (else `ERR_CLIENT_NOT_ACTIVE`) with a verified assessment (else `ERR_ASSESSMENT_REQUIRED`) and a fund that is not `CLOSED` (else `ERR_FUND_CLOSED`). From `DRAFT`, the application moves to `SUBMITTED` when the fund is `OPEN` — any other non-admitting application state is `ERR_GRANT_NOT_REVIEWABLE` — and parks as `QUEUED` when the fund is `EXHAUSTED`, waiting for the fund to reopen. Queued promotion is automatic: when a fund flips from `EXHAUSTED` back to `OPEN` within a single atomic event, the queued application on that fund with the earliest `created_at` moves to `SUBMITTED`, at most one promotion per reopen event.

Review begins when a `GrantReviewer` claims a `SUBMITTED` application, moving it to `UNDER_REVIEW` and stamping `reviewed_by` with the acting reviewer's staff id. Claiming from any other state is `ERR_GRANT_NOT_REVIEWABLE`, and claiming is barred when the acting reviewer's staff id equals the application's `created_by_user_id` — the segregation-of-duties check, rejected with `ERR_SOD_CONFLICT`. Once under review, the recorded reviewer alone drives the next steps; any other reviewer is `ERR_FORBIDDEN_OWNERSHIP`. Requesting more information moves `UNDER_REVIEW` to `MORE_INFO_REQUESTED` and records the reviewer's `info_request_notes`. The applicant's resubmission — again by the creating client or an `IntakeCoordinator`, with the same client-active and verified-assessment gates — moves `MORE_INFO_REQUESTED` back to `SUBMITTED`, clearing `reviewed_by` so the application re-enters the open review pool.

Approval sizes the award at the moment of decision, computed strictly from pre-approval state. The approved amount is the smallest of four caps: the application's `requested_cents`; the 150,000-cent per-award cap; the fund's `remaining_committed_basis` read before this approval commits anything; and the client's remaining lifetime room, 300,000 cents minus the client's `lifetime_grant_cents`. An approval requires the application `UNDER_REVIEW` (else `ERR_GRANT_NOT_REVIEWABLE`), the acting reviewer equal to `reviewed_by` (else `ERR_FORBIDDEN_OWNERSHIP`), and a current `expected_fund_version` per §2.8. When the sized award would be zero or negative — fund remainder or lifetime room exhausted — approval is rejected with `ERR_AWARD_CAP_EXHAUSTED`. On success the application moves to `APPROVED` with `approved_cents` and `approved_at` stamped; the fund's `committed_cents` grows by the approved amount, both remainder bases recompute, and the fund's `version` advances by one. Should that approval bring `remaining_committed_basis` to exactly zero while committed money exists, the fund flips automatically from `OPEN` to `EXHAUSTED`, and subsequent submissions against it park as `QUEUED`. Denial, likewise reserved to the recorded reviewer, moves `UNDER_REVIEW` to the terminal `DENIED` state and records the reviewer's `decision_rationale`.

Disbursement is the fast final step, executed by a `HubAdmin`. The application must be `APPROVED` (else `ERR_GRANT_NOT_REVIEWABLE`); the two-person rule bars the disbursing admin whose `X-User-ID` equals the application's `reviewed_by` (else `ERR_SOD_CONFLICT`); and the logical clock must be no later than 72 hours after `approved_at`, inclusive — a disbursement at exactly the 72-hour mark is admitted, anything later is `ERR_DISBURSE_WINDOW_LAPSED`. On success the application is `DISBURSED` with `disbursed_at` stamped; the fund's `committed_cents` falls and its `disbursed_cents` rises by the approved amount, both bases recompute, and the fund's `version` advances by one; and the client's `lifetime_grant_cents` grows by the approved amount. When the release of committed money lifts `remaining_committed_basis` back above zero, the fund flips from `EXHAUSTED` to `OPEN`, and that flip itself triggers the queued-promotion rule above. An approval never disbursed in time expires instead: the sweep moves `APPROVED` to `EXPIRED` once the logical clock is strictly past the 72-hour mark, releasing `committed_cents`, recomputing the bases, advancing the fund's `version`, and running the same reopen-and-promote cascade. Either party on the applicant side — the creating client or an `IntakeCoordinator` — may withdraw an application from `DRAFT`, `SUBMITTED`, or `QUEUED`, moving it to `WITHDRAWN`; withdrawal from any later state is `ERR_GRANT_NOT_REVIEWABLE`.

Finally, a `HubAdmin` may close a fund, moving it from `OPEN` or `EXHAUSTED` to `CLOSED`. Closing is rejected with `ERR_FUND_HAS_OPEN_APPLICATIONS` while any application against the fund occupies `SUBMITTED`, `QUEUED`, `UNDER_REVIEW`, `MORE_INFO_REQUESTED`, or `APPROVED` — money still in flight must resolve first.

### 3.6. Shelter Coordination: Beds, Stay Windows, and the No-Show Policy

The shelter registry tracks individual beds. A `ShelterCoordinator` or `HubAdmin` registers a bed with its `shelter_site`, a `bed_label` unique within that site (duplicates are `ERR_DUPLICATE_BED_LABEL`), and an optional `features` list drawn from `ADA_ACCESSIBLE`, `FAMILY_UNIT`, and `PET_FRIENDLY`, defaulting to empty. A `PET_FRIENDLY` bed imposes a one-day sanitation buffer after each stay, which the interval rules below encode. A new bed is `AVAILABLE`. The registry is listable with optional `shelter_site` and `status` filters. A bed's status may be patched between `AVAILABLE` and `OUT_OF_SERVICE`, except that marking a bed `OUT_OF_SERVICE` while a stay is `OCCUPIED` on it is rejected with `ERR_BED_OCCUPIED`.

Reserving a stay is a `ShelterCoordinator` act with a payload of `bed_id`, `check_in_date`, and `planned_nights`, and it runs a layered admission. The client must be `ACTIVE` (else `ERR_CLIENT_NOT_ACTIVE`) and hold a verified assessment (else `ERR_ASSESSMENT_REQUIRED`). The stay window must be sane: `check_in_date` within the booking horizon from the logical today through 13 days ahead inclusive, and `planned_nights` between 1 and 14 inclusive, with violations rejected as `ERR_STAY_WINDOW_INVALID`. Placement then checks the bed and the client. The bed must be `AVAILABLE` (else `ERR_BED_OUT_OF_SERVICE`). The bed must be free for the requested interval under the bed rule below (else `ERR_BED_NOT_AVAILABLE`). The client must have no intersecting nights under the client rule below (else `ERR_CLIENT_STAY_OVERLAP`). And the client's `shelter_restricted` flag must be false (else `ERR_SHELTER_RESTRICTED`). Shelter eligibility is deliberately narrow: the verified assessment's `housing_status` must be `UNSTABLE` or `HOMELESS`; a `STABLE` or `COST_BURDENED` household is not shelter-eligible and is rejected with `ERR_NOT_HOUSING_INSECURE`. A created stay is `RESERVED`, with `actual_check_out_date` null until departure and `no_show_marked_at` null unless a no-show is ever marked. Two dates are computed at creation and frozen on the record: `check_out_exclusive`, the check-in date plus `planned_nights` days — the morning the bed turns over — and `buffer_until_exclusive`, one day beyond checkout for a `PET_FRIENDLY` bed and equal to checkout otherwise. Stays are listable with optional `client_id`, `bed_id`, and `status` filters; a `Client`-role caller sees only its own stays.

The bed rule treats a bed as occupied over the half-open interval from a stay's `check_in_date` up to but not including its `buffer_until_exclusive`: a new stay conflicts with an existing `RESERVED` or `OCCUPIED` stay on the same bed when the new check-in falls before the existing stay's buffer-until date and the existing check-in falls before the new stay's buffer-until date. Back-to-back turnover — the new check-in landing exactly on the existing stay's checkout date — is allowed on an ordinary bed, because the buffer equals the checkout date; on a `PET_FRIENDLY` bed the next check-in must be at least one day after checkout, the sanitation buffer. The client rule is deliberately different in interval semantics: a client's nights are the closed set from `check_in_date` through the day before `check_out_exclusive`, and a new stay for the same client conflicts with an existing `RESERVED` or `OCCUPIED` stay when their night sets intersect. Same-day turnover — checking in on the day the previous stay checks out — is therefore allowed for the client, whose nights do not intersect; but it remains disallowed on a `PET_FRIENDLY` bed, where the bed rule's buffer still blocks it.

Arrival is marked by a `ShelterCoordinator` checking the stay in: the stay must be `RESERVED` (else `ERR_STAY_NOT_ACTIONABLE`), the logical date must be the `check_in_date` or the day immediately after it (else `ERR_STAY_WINDOW_INVALID`), and the client must be `ACTIVE` (else `ERR_CLIENT_NOT_ACTIVE`); the stay becomes `OCCUPIED`. Departure is marked by checking out: the stay must be `OCCUPIED` (else `ERR_STAY_NOT_ACTIONABLE`), `actual_check_out_date` is set to the logical date, and the client's `risk_tier` is recomputed per the tier rule of §3.2. Cancelling — by a `ShelterCoordinator` or `HubAdmin`, or by the system during client exit — moves a `RESERVED` stay to `CANCELLED` and frees the bed interval it held.

The no-show policy runs through the sweep. A stay still `RESERVED` once the logical date has moved past the day after its `check_in_date` flips to `NO_SHOW` with `no_show_marked_at` stamped at the logical now. Each no-show recomputes the client's `shelter_no_show_count_90d`; when that count reaches 2, the client's `shelter_restricted` becomes true, and subsequent stay creation is rejected with `ERR_SHELTER_RESTRICTED`.

### 3.7. The Partner Agency Network and Warm-Handoff Referrals

The hub's referral network rests on a directory of partner agencies administered by a `HubAdmin`. Registering an agency takes an `agency_name` that must be unique (duplicates are `ERR_DUPLICATE_AGENCY`), a non-empty `service_categories` list drawn from `SNAP_APPLICATION`, `CHILDCARE_SUBSIDY`, `HOUSING_PLACEMENT`, `LEGAL_AID`, and `MENTAL_HEALTH`, a `weekly_capacity` of at least 1 bounding concurrent active referrals, and an optional `accepts_walk_ins` flag defaulting to false. A new agency is `ACTIVE` with an `active_referral_count` of 0 — that counter tracks the agency's referrals currently in `SENT`, `ACKNOWLEDGED`, or `APPOINTMENT_BOOKED`. The directory is deliberately transparent: clients, agency representatives, and every staff role may browse it, with optional `status` and `service_category` filters. Configuration updates may change `weekly_capacity`, `service_categories`, or `accepts_walk_ins`, with one guardrail — capacity may not be set below the agency's current `active_referral_count` (else `ERR_CAPACITY_BELOW_ACTIVE`). Pausing moves an `ACTIVE` agency to `PAUSED`, and resuming reverses it (the wrong starting state is `ERR_INVALID_STATE`); a paused agency blocks new sends and resends with `ERR_AGENCY_NOT_ACTIVE`, while its existing `SENT` and `ACKNOWLEDGED` referrals remain actionable.

A referral is initiated by an `IntakeCoordinator`, `BenefitsCounselor`, or `ShelterCoordinator` for a client who must be `ACTIVE` (else `ERR_CLIENT_NOT_ACTIVE`). The payload names the target `agency_id`, a `service_category`, an optional `warm_handoff` flag defaulting to false, and optional free-text `notes`. Two referential checks bind the referral to the agency's published capabilities: the `service_category` must be among the agency's `service_categories` (else `ERR_CATEGORY_NOT_SERVED`), and requesting a `warm_handoff` — a staff-assisted, unscheduled introduction — requires the agency's `accepts_walk_ins` to be true (else `ERR_WALK_INS_NOT_ACCEPTED`). Capacity is pre-checked at initiation per the admission rule below, but an initiated referral does not itself occupy capacity. A new referral is `INITIATED`, with `sent_at` and `ack_due_at` null until it is first sent and `decline_reason` null unless the agency declines it. The collection supports `client_id`, `agency_id`, and `status` filters; a `Client` sees only its own referrals, and a `PartnerAgencyRep` only its own agency's.

Agency admission works as follows. An agency admits while its `active_referral_count` is below its `weekly_capacity`; a count already equal to capacity rejects with `ERR_AGENCY_CAPACITY_FULL`. Clients whose current `risk_tier` is `CRISIS` receive overflow headroom: they are admitted while the active count is below the capacity multiplied by 1.2 and rounded down to a whole number; at or beyond that ceiling even `CRISIS` referrals are rejected with `ERR_AGENCY_CAPACITY_FULL`. The same rule is re-evaluated at resend time against the client's current tier.

Sending, by the same three hub roles, moves an `INITIATED` referral to `SENT` (any other state is `ERR_REFERRAL_NOT_ACTIONABLE`), requires the agency `ACTIVE` (else `ERR_AGENCY_NOT_ACTIVE`), stamps `sent_at` with the logical now, sets `ack_due_at` exactly 120 hours later — the agency's five-day acknowledgement deadline — and increments the agency's `active_referral_count` by one.

Everything after the send happens on the agency's side, driven by a `PartnerAgencyRep` whose `X-User-ID` must equal the referral's `agency_id` (else `ERR_FORBIDDEN_OWNERSHIP`). Acknowledging moves `SENT` to `ACKNOWLEDGED`. Booking an appointment moves `ACKNOWLEDGED` to `APPOINTMENT_BOOKED` and carries an `appointment_date` no earlier than the logical today (an earlier date is `ERR_INVALID_REQUEST`). Recording service delivered moves `APPOINTMENT_BOOKED` to the terminal `SERVICE_RECEIVED` and decrements the agency's `active_referral_count` by one. Declining is available from `SENT` or `ACKNOWLEDGED`, records the agency's `decline_reason`, moves the referral to `DECLINED`, and decrements the counter. Any of these agency actions from a non-admitting state is `ERR_REFERRAL_NOT_ACTIONABLE`.

The hub side retains two controls. Withdrawing, by the three hub roles or by the system during client exit, moves a referral from `INITIATED` or `SENT` to `WITHDRAWN` (else `ERR_REFERRAL_NOT_ACTIONABLE`); withdrawing a `SENT` referral decrements the agency's `active_referral_count`. And when an agency lets the deadline lapse, the sweep expires the referral: a `SENT` referral flips to `EXPIRED` strictly once the logical clock passes `ack_due_at` — exactly at the deadline it remains `SENT` — and the expiry decrements the agency's counter, freeing capacity for subsequent referrals. An expired referral is not dead: resending, by the three hub roles, moves `EXPIRED` back to `SENT`, re-checks that the agency is `ACTIVE`, re-runs the capacity admission against the client's current risk tier (else `ERR_AGENCY_CAPACITY_FULL`), restamps `sent_at` and `ack_due_at` for a fresh 120-hour window, and increments the counter again.

### 3.8. Outreach Programming and Stigma-Reducing Events

Outreach events normalize asking for help. A `HubAdmin` creates an event with a `title`, an `event_date` giving its logical start, a `capacity` of at least 1 bounding how many registrations may hold `REGISTERED` at any moment, a `stigma_theme` of `NORMALIZATION`, `PEER_LED`, `FACULTY_TRAINING`, or `RESOURCE_FAIR`, and an optional `anonymous_attendance_allowed` flag defaulting to true. A new event is `PLANNED` with its counts zeroed: `registered_count` tallies registrations in `REGISTERED`, and `attended_count` tallies those in `ATTENDED`. The event list is public — even `Anonymous` callers may browse it, a stigma-reduction choice — with an optional `status` filter.

A `HubAdmin` opens a `PLANNED` event for registration (from any other state, `ERR_INVALID_STATE`), moving it to `OPEN`. Thereafter the event's fullness is system-maintained: when `registered_count` reaches `capacity` the event flips automatically from `OPEN` to `FULL` and new registrations are rejected with `ERR_EVENT_FULL`; when a cancellation drops the count back below capacity the event flips from `FULL` to `OPEN` and registrations are accepted again. Completion moves an `OPEN` or `FULL` event to `COMPLETED`, either by a `HubAdmin` closing it out or by the sweep once the logical clock reaches 24 hours past `event_date`; completion is what makes registrations markable as attended. Cancelling — from `PLANNED`, `OPEN`, or `FULL` (else `ERR_INVALID_STATE`) — moves the event to `CANCELLED` and cascades every `REGISTERED` registration to `CANCELLED`, recomputing `registered_count`.

Registration is open to the client personally, an `IntakeCoordinator`, or a `HubAdmin`, with a payload naming the `client_id` and an optional `display_alias` — the name shown on the attendee list — which defaults to the client's `alias_name`; events that disallow anonymous attendance expect that default rather than a display-only alias. Admission requires the event `OPEN` — against a `FULL` event the rejection is `ERR_EVENT_FULL`, and against an event in any other non-open state the generic state gate rejects with `ERR_INVALID_STATE` — the logical now strictly before `event_date` (registration at or after the start is `ERR_EVENT_PAST`), and the client `ACTIVE` (else `ERR_CLIENT_NOT_ACTIVE`). Uniqueness holds per event and client among non-cancelled registrations: a second live registration for the same pair is rejected with `ERR_ALREADY_REGISTERED`, while re-registering a client whose earlier row was cancelled reactivates that very row from `CANCELLED` back to `REGISTERED` rather than creating a duplicate. Each admission increments the event's `registered_count` and may flip the event from `OPEN` to `FULL`. Registrations are listable with optional `event_id`, `client_id`, and `status` filters; a `Client` sees only its own.

Two terminal actions complete the picture. Cancelling a registration — by the client, an `IntakeCoordinator`, a `HubAdmin`, or the system via event cancellation or client exit — moves `REGISTERED` to `CANCELLED` (else `ERR_REGISTRATION_NOT_ACTIONABLE`), decrements `registered_count`, and flips the event from `FULL` back to `OPEN` when the count drops below capacity. Marking attendance, by a `HubAdmin`, moves `REGISTERED` to `ATTENDED` — it requires the registration still `REGISTERED` (else `ERR_REGISTRATION_NOT_ACTIONABLE`) and the event already `COMPLETED` (else `ERR_EVENT_NOT_COMPLETED`) — and increments `attended_count`.

### 3.9. Outcome Tracking and the Usage Summary

The hub reports outcomes through a single de-identified usage summary, restricted to `HubAdmin`. Optional `from_date` and `to_date` parameters bound an inclusive window running from 00:00:00.000Z on `from_date` through 23:59:59.999Z on `to_date`; an omitted bound is open-ended. Nine aggregates are computed against the window, each pinned to its own timestamp field. `clients_active` counts clients currently `ACTIVE` — a point-in-time figure, window-agnostic. `visits_completed` counts pantry visits `COMPLETED` with `visit_date` in the window, and `points_redeemed` sums their `points_spent`. `screenings_by_program` counts screenings created in the window, broken out by `SNAP`, `CHILDCARE`, and `HOUSING`. `grants_approved_cents` sums `approved_cents` over applications whose `approved_at` falls in the window, and `grants_disbursed_cents` the same over `disbursed_at`. `referrals_by_status` counts referrals created in the window across all eight referral statuses. `shelter_nights_served` sums, over stays `CHECKED_OUT` with `actual_check_out_date` in the window, the nights between `check_in_date` and the actual check-out date. `event_attendance` counts registrations `ATTENDED` whose event's `event_date` falls in the window. All figures are integer counts, cents, or nights; the report contains counts and sums only — no client-level data.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code; operations that modify an existing resource or drive a state transition return `200 OK`, as do all reads and list endpoints. Error responses use the codes catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Advance the logical clock (forward only; does not fire transitions) | HubAdmin |
| POST | `/_sweeps/run_pending_transitions` | Run all pending clock-driven transitions in pinned order | HubAdmin |
| POST | `/staff` | Register a staff member | HubAdmin |
| GET | `/staff` | List staff with optional filters | HubAdmin |
| POST | `/clients` | Register a client (self-service or staff-assisted) | Anonymous, IntakeCoordinator, HubAdmin |
| GET | `/clients` | List clients with filters | IntakeCoordinator, PantryStaff, BenefitsCounselor, GrantReviewer, ShelterCoordinator, HubAdmin |
| GET | `/clients/{cid}` | Read one client (Client role reads only its own record) | Client, IntakeCoordinator, PantryStaff, BenefitsCounselor, GrantReviewer, ShelterCoordinator, HubAdmin |
| POST | `/clients/{cid}/suspend` | Suspend an ACTIVE client; auto-voids any checked-in visit | HubAdmin |
| POST | `/clients/{cid}/reinstate` | Reinstate a SUSPENDED client | HubAdmin |
| POST | `/clients/{cid}/exit` | Exit a client; unwinds stays, referrals, registrations, open visit, draft assessments | IntakeCoordinator, HubAdmin |
| POST | `/clients/{cid}/assessments` | Create a DRAFT intake assessment | Client, IntakeCoordinator |
| GET | `/assessments` | List assessments (confidential) | Client, IntakeCoordinator, BenefitsCounselor, GrantReviewer, HubAdmin |
| GET | `/assessments/{aid}` | Read one assessment (confidential) | Client, IntakeCoordinator, BenefitsCounselor, GrantReviewer, HubAdmin |
| POST | `/clients/{cid}/assessments/{aid}/submit` | Submit a DRAFT assessment; freezes income ratio and eligibility band | Client, IntakeCoordinator |
| POST | `/clients/{cid}/assessments/{aid}/verify` | Verify a SUBMITTED assessment; supersedes prior verified; OCC on client version | IntakeCoordinator |
| POST | `/clients/{cid}/assessments/{aid}/return` | Return a SUBMITTED assessment for corrections | IntakeCoordinator |
| POST | `/clients/{cid}/assessments/{aid}/revise` | Reopen a RETURNED assessment to DRAFT, overwriting supplied fields | Client, IntakeCoordinator |
| POST | `/pantry-items` | Create a pantry item with initial stock | HubAdmin |
| GET | `/pantry-items` | List pantry items (clients may browse) | Client, IntakeCoordinator, PantryStaff, BenefitsCounselor, GrantReviewer, ShelterCoordinator, HubAdmin |
| PATCH | `/pantry-items/{iid}` | Update pricing/limits config; OCC on item version | HubAdmin |
| POST | `/pantry-items/{iid}/restock` | Add stock | PantryStaff, HubAdmin |
| POST | `/pantry-items/{iid}/discontinue` | Discontinue an item (blocks new line-item adds) | HubAdmin |
| POST | `/clients/{cid}/pantry-visits` | Check a client in to the pantry (frequency and open-visit limits) | PantryStaff |
| GET | `/pantry-visits` | List visits (Client sees only own) | Client, PantryStaff, HubAdmin |
| GET | `/pantry-visits/{vid}` | Read one visit (Client only own) | Client, PantryStaff, HubAdmin |
| POST | `/pantry-visits/{vid}/line-items` | Add an item line to an open visit; pins points at add time | PantryStaff |
| GET | `/visit-line-items` | List line items filtered by visit and/or item | PantryStaff, HubAdmin |
| GET | `/visit-line-items/{liid}` | Read one line item | PantryStaff, HubAdmin |
| POST | `/pantry-visits/{vid}/checkout` | Complete a visit: points admission, then stock decrement per line | PantryStaff |
| POST | `/pantry-visits/{vid}/void` | Void a visit; from COMPLETED restores stock and points | PantryStaff, HubAdmin |
| POST | `/clients/{cid}/screenings` | Open a benefits screening; counselor auto-assigned | IntakeCoordinator, BenefitsCounselor |
| GET | `/screenings` | List screenings (confidential) | Client, IntakeCoordinator, BenefitsCounselor, HubAdmin |
| GET | `/screenings/{sid}` | Read one screening (confidential) | Client, IntakeCoordinator, BenefitsCounselor, HubAdmin |
| POST | `/screenings/{sid}/score` | Compute score, band, and SNAP estimate from the verified assessment | BenefitsCounselor |
| POST | `/screenings/{sid}/assist` | Record application assistance (eligible bands only) | BenefitsCounselor |
| POST | `/screenings/{sid}/submit-application` | Mark the assisted application submitted to the agency | BenefitsCounselor |
| POST | `/screenings/{sid}/determine` | Record the agency determination | BenefitsCounselor |
| POST | `/screenings/{sid}/withdraw` | Withdraw a screening from any pre-terminal state | BenefitsCounselor |
| POST | `/grant-funds` | Create a fiscal-year grant fund | HubAdmin |
| GET | `/grant-funds/{fid}` | Read a fund including both remaining bases | GrantReviewer, HubAdmin |
| POST | `/grant-funds/{fid}/close` | Close a fund with no open applications | HubAdmin |
| POST | `/clients/{cid}/grant-applications` | Create a DRAFT emergency grant application | Client, IntakeCoordinator, GrantReviewer |
| GET | `/grant-applications` | List grant applications (Client sees only own) | Client, IntakeCoordinator, GrantReviewer, HubAdmin |
| GET | `/grant-applications/{gid}` | Read one application (Client only own) | Client, IntakeCoordinator, GrantReviewer, HubAdmin |
| POST | `/grant-applications/{gid}/submit` | Submit from DRAFT (OPEN funds) or QUEUED parking (EXHAUSTED); resubmit from MORE_INFO_REQUESTED | Client, IntakeCoordinator |
| POST | `/grant-applications/{gid}/begin-review` | Reviewer claims a SUBMITTED application; enforces segregation of duties | GrantReviewer |
| POST | `/grant-applications/{gid}/request-info` | Send the application back for more information | GrantReviewer |
| POST | `/grant-applications/{gid}/approve` | Approve with award sizing; OCC on fund version | GrantReviewer |
| POST | `/grant-applications/{gid}/deny` | Deny the application | GrantReviewer |
| POST | `/grant-applications/{gid}/disburse` | Disburse an APPROVED application within 72 hours; two-person rule | HubAdmin |
| POST | `/grant-applications/{gid}/withdraw` | Withdraw from DRAFT, SUBMITTED, or QUEUED | Client, IntakeCoordinator |
| POST | `/shelter-beds` | Register a shelter bed | ShelterCoordinator, HubAdmin |
| GET | `/shelter-beds` | List beds | IntakeCoordinator, ShelterCoordinator, HubAdmin |
| PATCH | `/shelter-beds/{bid}` | Set bed status; OUT_OF_SERVICE blocked while occupied | ShelterCoordinator, HubAdmin |
| POST | `/clients/{cid}/shelter-stays` | Reserve a stay (eligibility, window, overlap, and restriction rules) | ShelterCoordinator |
| GET | `/shelter-stays` | List stays (Client sees only own) | Client, ShelterCoordinator, HubAdmin |
| GET | `/shelter-stays/{sid}` | Read one stay (Client only own) | Client, ShelterCoordinator, HubAdmin |
| POST | `/shelter-stays/{sid}/check-in` | Mark arrival on the check-in date or the next day | ShelterCoordinator |
| POST | `/shelter-stays/{sid}/check-out` | Mark departure; recomputes client risk tier | ShelterCoordinator |
| POST | `/shelter-stays/{sid}/cancel` | Cancel a RESERVED stay, freeing the bed interval | ShelterCoordinator, HubAdmin |
| POST | `/partner-agencies` | Register a partner agency | HubAdmin |
| GET | `/partner-agencies` | List agencies (transparent to clients and representatives) | Client, IntakeCoordinator, PantryStaff, BenefitsCounselor, ShelterCoordinator, HubAdmin, PartnerAgencyRep |
| PATCH | `/partner-agencies/{aid}` | Update capacity, categories, or walk-ins; capacity floored at active count | HubAdmin |
| POST | `/partner-agencies/{aid}/pause` | Pause an agency (blocks send and resend) | HubAdmin |
| POST | `/partner-agencies/{aid}/resume` | Resume a paused agency | HubAdmin |
| POST | `/clients/{cid}/referrals` | Initiate a referral with capacity and capability checks | IntakeCoordinator, BenefitsCounselor, ShelterCoordinator |
| GET | `/referrals` | List referrals (Client sees own; representative sees own agency) | Client, IntakeCoordinator, BenefitsCounselor, ShelterCoordinator, HubAdmin, PartnerAgencyRep |
| GET | `/referrals/{rid}` | Read one referral (Client only own; representative only own agency) | Client, IntakeCoordinator, BenefitsCounselor, ShelterCoordinator, HubAdmin, PartnerAgencyRep |
| POST | `/referrals/{rid}/send` | Send an INITIATED referral; stamps the acknowledgement deadline | IntakeCoordinator, BenefitsCounselor, ShelterCoordinator |
| POST | `/referrals/{rid}/acknowledge` | Agency acknowledges a SENT referral | PartnerAgencyRep |
| POST | `/referrals/{rid}/book-appointment` | Agency books an appointment (date not before today) | PartnerAgencyRep |
| POST | `/referrals/{rid}/record-service` | Agency records service delivered | PartnerAgencyRep |
| POST | `/referrals/{rid}/decline` | Agency declines a SENT or ACKNOWLEDGED referral | PartnerAgencyRep |
| POST | `/referrals/{rid}/withdraw` | Hub withdraws an INITIATED or SENT referral | IntakeCoordinator, BenefitsCounselor, ShelterCoordinator |
| POST | `/referrals/{rid}/resend` | Resend an EXPIRED referral; re-checks agency status and capacity | IntakeCoordinator, BenefitsCounselor, ShelterCoordinator |
| POST | `/outreach-events` | Create an outreach event (PLANNED) | HubAdmin |
| GET | `/outreach-events` | Public event list (anonymous browsing allowed) | Anonymous, Client, IntakeCoordinator, PantryStaff, BenefitsCounselor, GrantReviewer, ShelterCoordinator, HubAdmin |
| POST | `/outreach-events/{eid}/open` | Open a PLANNED event for registration | HubAdmin |
| POST | `/outreach-events/{eid}/complete` | Complete an OPEN or FULL event | HubAdmin |
| POST | `/outreach-events/{eid}/cancel` | Cancel an event; cascades registrations to CANCELLED | HubAdmin |
| POST | `/outreach-events/{eid}/registrations` | Register a client; reactivates a prior cancelled row | Client, IntakeCoordinator, HubAdmin |
| GET | `/event-registrations` | List registrations filtered by event and/or client (Client sees only own) | Client, IntakeCoordinator, HubAdmin |
| GET | `/event-registrations/{rid}` | Read one registration (Client only own) | Client, IntakeCoordinator, HubAdmin |
| POST | `/event-registrations/{rid}/cancel` | Cancel a registration; may flip the event back to OPEN | Client, IntakeCoordinator, HubAdmin |
| POST | `/event-registrations/{rid}/mark-attended` | Mark attendance after the event completed | HubAdmin |
| GET | `/reports/usage-summary` | De-identified outcome and usage aggregates | HubAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error live with the workflows that raise them in §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_CONFIDENTIAL` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_CLIENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ASSESSMENT_REQUIRED` | 409 Conflict |
| `ERR_ASSESSMENT_NOT_EDITABLE` | 409 Conflict |
| `ERR_VISIT_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_VISIT_ALREADY_OPEN` | 409 Conflict |
| `ERR_VISIT_NOT_OPEN` | 409 Conflict |
| `ERR_ITEM_NOT_AVAILABLE` | 409 Conflict |
| `ERR_SCREENING_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_NO_COUNSELOR_AVAILABLE` | 409 Conflict |
| `ERR_GRANT_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_SOD_CONFLICT` | 409 Conflict |
| `ERR_AWARD_CAP_EXHAUSTED` | 409 Conflict |
| `ERR_FUND_CLOSED` | 409 Conflict |
| `ERR_FUND_HAS_OPEN_APPLICATIONS` | 409 Conflict |
| `ERR_DISBURSE_WINDOW_LAPSED` | 409 Conflict |
| `ERR_BED_OUT_OF_SERVICE` | 409 Conflict |
| `ERR_BED_OCCUPIED` | 409 Conflict |
| `ERR_BED_NOT_AVAILABLE` | 409 Conflict |
| `ERR_CLIENT_STAY_OVERLAP` | 409 Conflict |
| `ERR_SHELTER_RESTRICTED` | 409 Conflict |
| `ERR_STAY_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_AGENCY_NOT_ACTIVE` | 409 Conflict |
| `ERR_AGENCY_CAPACITY_FULL` | 409 Conflict |
| `ERR_CAPACITY_BELOW_ACTIVE` | 409 Conflict |
| `ERR_REFERRAL_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_EVENT_FULL` | 409 Conflict |
| `ERR_EVENT_NOT_COMPLETED` | 409 Conflict |
| `ERR_ALREADY_REGISTERED` | 409 Conflict |
| `ERR_REGISTRATION_NOT_ACTIONABLE` | 409 Conflict |
| `ERR_DUPLICATE_BED_LABEL` | 409 Conflict |
| `ERR_DUPLICATE_AGENCY` | 409 Conflict |
| `ERR_DUPLICATE_STAFF_EMAIL` | 409 Conflict |
| `ERR_DUPLICATE_FUND` | 409 Conflict |
| `ERR_DUPLICATE_ITEM` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CONSENT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_EMPTY_CHECKOUT` | 422 Unprocessable Entity |
| `ERR_ITEM_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_POINTS_BALANCE_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_STAY_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_NOT_HOUSING_INSECURE` | 422 Unprocessable Entity |
| `ERR_CATEGORY_NOT_SERVED` | 422 Unprocessable Entity |
| `ERR_WALK_INS_NOT_ACCEPTED` | 422 Unprocessable Entity |
| `ERR_EVENT_PAST` | 422 Unprocessable Entity |
