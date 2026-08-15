# Block Party Street Closure API — Product Requirements Document

## 1. Introduction

Every summer, residents across the city close their blocks for street parties — and every closure touches the same civic machinery: the neighbors must demonstrably support it, traffic control has to keep an emergency lane open, amplified sound has to respect quiet hours, liability has to be insured or formally waived, barricades and cones have to come out of a finite depot inventory, and somebody has to be financially on the hook for cleanup. Today each of these concerns is handled in a different office with a different paper form, and disputes about who approved what — or who returned how many barricades, and when — are routine.

This document specifies the Block Party Street Closure API, the platform that coordinates that entire lifecycle as one auditable workflow. The API governs the street segment registry, the neighbor petition with its jurisdiction- and zoning-sensitive signature thresholds, the permit application with its lead-time and window-conflict rules, three independent review lanes (traffic control, amplified sound, insurance), a quota-driven equipment reservation pipeline with dispatch, return, late and shortage accounting, a shared-cost collection pool for the block, a refundable deposit whose forfeitures demote organizer standing, and the post-event cleanup report that closes the event out. Responsibilities are deliberately segregated across distinct municipal roles — plan reviewers, safety reviewers, permit adjudicators, and depot officers — and every deadline, window, and expiry in the system reads from a single logical clock so that time-dependent behavior is deterministic and testable.

## 2. Global Specifications & System-Wide Principles

This section defines the contract-level rules that apply uniformly across the API: authentication, response shape, pagination, resource identity, time, validation ordering, concurrency control, monetary precision, depot stock conservation, cascade behavior, and nested-resource retrieval.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. The platform recognizes exactly eight roles: `Anonymous`, `Organizer`, `Neighbor`, `TrafficReviewer`, `SafetyReviewer`, `PermitOfficer`, `DepotOfficer`, and `CityAdmin`. A request missing either header, or presenting an `X-User-Role` value outside that set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The `Organizer` role is entity-backed: when `X-User-Role` is `Organizer`, `X-User-ID` is the `id` of the acting Organizer record, and ownership checks on any resource that traces back to an Organizer — a petition, a permit application, and everything created beneath an application such as plans, insurance records, reservations, the pool, the deposit, and the post-event report — compare the resource's owning `organizer_id` to `X-User-ID`; a mismatch is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403). An organizer whose `standing` has fallen to `SUSPENDED` is further barred from creating petitions or permit applications and is rejected with `ERR_ORGANIZER_SUSPENDED` (HTTP 403).

All remaining roles — `Anonymous`, `Neighbor`, `TrafficReviewer`, `SafetyReviewer`, `PermitOfficer`, `DepotOfficer`, and `CityAdmin` — are opaque: for each of them, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record such identifiers where a workflow calls for attribution — for example as `reviewed_by` on a reviewed traffic plan, sound plan, or insurance record, as `dispatched_by` and `return_verified_by` on an equipment reservation, or as `inspected_by` on a post-event report — but it never compares them to any entity's `id`. Where segregation of duties matters (dispatch versus return verification), the comparison is between two recorded opaque identifiers, not between an identifier and an entity.

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

List endpoints paginate through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, accepts a minimum of 1, and is bounded above at 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Unless stated otherwise, every list endpoint returns resources sorted by `created_at` in ascending order. List responses expose the fields `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every primary resource — Organizer, StreetSegment, Petition, PetitionSignature, PermitApplication, TrafficControlPlan, SoundPlan, InsuranceCertificate, EquipmentStock, EquipmentReservation, CostSharePool, Contribution, Deposit, and PostEventReport — carries a uniform set of system-managed fields:

- `id` (string): a server-minted UUID with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every modification of the resource, including modifications caused by cascades initiated elsewhere.
- `version` (integer): a server-managed integer that increments by one on every mutation of the resource, again including cascade-driven mutations.

The one exception is the ChargeEntry posted against a deposit: a charge entry carries only `id` and `created_at`. Both `updated_at` and `version` are absent from charge entries, because a posted charge is immutable once written.

### 2.5. The Logical Clock

All temporal reasoning in the platform reads a single logical clock, exposed to clients as `current_utc`. Before the clock has ever been set, it reads exactly 2026-05-01T00:00:00Z, and it never falls back to wall-clock time. A `CityAdmin` may advance the clock through an admin-only test-driving capability that takes a `to_iso8601` instant and sets the logical clock to it. Every deadline, window, expiry, and time-weighted computation in this document — jurisdiction lead times, segment window conflicts, the equipment dispatch window, the post-event report window, insurance expiry relative to the event date, lazy application expiry, late-return day counts, and membership of reservations in a stock's reserved tally — evaluates against this logical clock and nothing else.

### 2.6. Validation Order of Evaluation

When several rules could reject the same request, the platform evaluates validation classes in a fixed priority order, and the earliest failing class determines the error returned. The order is:

1. **Authentication** — presence of the `X-User-ID` and `X-User-Role` headers and recognition of the role (`ERR_UNAUTHENTICATED`).
2. **Authorization** — the role is permitted for the endpoint; for entity-backed `Organizer` calls the `X-User-ID` matches the owning organizer of the target resource (`ERR_NOT_RESOURCE_OWNER`); and the caller's standing permits creation (`ERR_ORGANIZER_SUSPENDED`). Other role rejections surface as `ERR_UNAUTHORIZED`.
3. **Existence** — path resource identifiers exist, validated left to right (`ERR_NOT_FOUND`).
4. **Optimistic concurrency** — where an endpoint is OCC-guarded, `expected_application_version` must match the application's current `version` (`ERR_STALE_APPLICATION_VERSION`). This class fires ahead of state gates.
5. **State gates** — the target resource is in a state that permits the transition, including cross-entity state gates such as a petition being `VERIFIED`, a pool being `OPEN`, billing being settled, or a petition not being `LOCKED` (`ERR_INVALID_STATE`, `ERR_PETITION_NOT_VERIFIED`, `ERR_PETITION_LOCKED`, `ERR_POOL_NOT_OPEN`, `ERR_BILLING_UNSETTLED`).
6. **Safety invariants** — the continuous emergency lane and its width, the per-segment barricade minimum, and the decibel cap (`ERR_EMERGENCY_LANE_VIOLATION`, `ERR_BARRICADE_PLAN_INSUFFICIENT`, `ERR_SOUND_DB_EXCEEDED`).
7. **Temporal rules** — event window shape, jurisdiction lead time, the day-of-week sound cutoff, the dispatch window, the report window, and insurance expiry (`ERR_EVENT_WINDOW_INVALID`, `ERR_LEAD_TIME_INSUFFICIENT`, `ERR_SOUND_CUTOFF_VIOLATION`, `ERR_DISPATCH_WINDOW_VIOLATION`, `ERR_REPORT_WINDOW_CLOSED`, `ERR_INSURANCE_EXPIRED`).
8. **Cross-entity readiness** — review lanes green, insurance satisfied, completion preconditions, and sound plans only where amplified sound was requested (`ERR_TCP_NOT_APPROVED`, `ERR_SOUND_PLAN_NOT_APPROVED`, `ERR_INSURANCE_NOT_SATISFIED`, `ERR_COMPLETION_PRECONDITIONS`, `ERR_SOUND_NOT_REQUESTED`).
9. **Uniqueness, overlap, and aggregate constraints** — duplicate signatures, singleton children, segment window conflicts, signature thresholds, equipment coverage, and stock availability (`ERR_DUPLICATE_SIGNATURE`, `ERR_DUPLICATE_RESOURCE`, `ERR_SEGMENT_WINDOW_CONFLICT`, `ERR_SIGNATURE_THRESHOLD_NOT_MET`, `ERR_EQUIPMENT_NOT_RESERVED`, `ERR_EQUIPMENT_UNAVAILABLE`).
10. **Fiscal rules, last** — deposit held before approval, contribution minimums, waiver caps and eligibility, and coverage amounts (`ERR_DEPOSIT_REQUIRED`, `ERR_CONTRIBUTION_BELOW_MIN`, `ERR_WAIVER_INELIGIBLE`, `ERR_INSURANCE_COVERAGE_INSUFFICIENT`, `ERR_WAIVER_AMOUNT_TOO_LARGE`).

Schema-level request validation accompanies request parsing: a missing required field, an unrecognized enum value, or a numeric constraint violation (for example a non-positive `expected_attendance`, or a `returned_units` outside its allowed range) is rejected with `ERR_INVALID_REQUEST` (HTTP 400). One nuance: `ERR_EVENT_WINDOW_INVALID` is likewise a 400-level shape error on the event window and is evaluated together with request validation, but when it competes with other business rules its conflict ordering follows the temporal class above.

### 2.7. Optimistic Concurrency Control

Exactly two write operations are guarded by optimistic concurrency, and both are guarded against the parent PermitApplication's `version`:

- **Updating a DRAFT application.** The request must carry `expected_application_version` equal to the application's current `version`. If another writer has advanced the application's version since the caller last read it, the update is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412), since any intervening mutation — including an insurance-certificate creation, which also bumps the application's version — invalidates the caller's view.
- **Creating an insurance record.** The request must likewise carry `expected_application_version` matching the application's current `version`. Because creating a record supersedes the application's prior unresolved insurance record, a stale value is rejected with `ERR_STALE_APPLICATION_VERSION` (HTTP 412): another writer has mutated the application, possibly superseding the very insurance record the caller saw, since the caller last observed it.

Both operations are non-optional in their OCC field — the field is required, not advisory. Endpoints not named above do not accept a version field at all.

### 2.8. Money, Units, and Rounding

All monetary values are integer cents; the API never accepts or returns fractional cents, and no monetary computation uses floating-point arithmetic. Where a calculation produces a non-integer intermediate, the result is rounded half up at the step that says so — specifically the per-line equipment tax, the large-event discount, and the administrative surcharge — and the resulting figures are stored as integers. Physical counts (signatures, households, barricades, cones, signs, speakers, units, attendees) are integers. Segment lengths and the emergency lane width are expressed in metres. Timestamps are ISO 8601 UTC. Two fields use specialized formats: `planned_sound_end` is an HH:MM local 24-hour time-of-day, and `expires_on` on an insurance record is a YYYY-MM-DD calendar date.

### 2.9. Depot Stock Conservation

Every EquipmentStock tracks three computed counters against the logical clock. `reserved_units` is the sum of `units` over reservations drawn on that stock whose `reservation_status` is `HELD` or `CONFIRMED` and whose parent application's buffered window contains the current logical time, where an application's buffered window runs from 24 hours before its `event_start_at` through 24 hours after its `event_end_at`, inclusive of both endpoints. `out_units` is the sum of outstanding units — `units` minus `returned_units` — over reservations currently `DISPATCHED`. `available_units` is `total_units` minus `reserved_units` minus `out_units`. The conservation invariant `total_units` equals `available_units` plus `reserved_units` plus `out_units` holds at every instant: dispatching moves units from the reserved tally into the out tally, recording a return subtracts the returned quantity from the out tally, and cancellation, recall, and closure release their reservation entirely.

### 2.10. Cascades and Hierarchical Status Alignment

State changes propagate across the aggregate boundary wherever the lifecycle demands it, and the platform performs these reconciliations itself rather than waiting for clients to ask. A petition slipping into deficiency suspends the applications built on it; a verified petition releases them back. Issuing a permit locks the petition and both plans and converts held reservations into confirmed, invoiced ones. Denial, cancellation, revocation, and expiry each unwind the application's commitments — reservations released, deposit settled, pool refunded — as one chain. Charges posted against a deposit can tip it into forfeiture, which in turn demotes the organizer's standing. Every hop of every such cascade is a real mutation of the affected resource: its state fields change, its `updated_at` refreshes, and its `version` increments where the resource carries one.

### 2.11. Nested Resource Retrieval

For any endpoint whose path contains more than one resource identifier, existence is validated left to right, one segment at a time, and the request is rejected with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource — before any child lookup, ownership comparison, or business rule runs. A request addressed to a signature under a petition that does not exist therefore fails on the petition, regardless of whether the signature identifier exists elsewhere.

## 3. Business Logic & Workflows

### 3.1. Organizers, Standing, and the Street Segment Registry

Participation begins with registration. An unauthenticated caller acting as `Anonymous` registers an organizer by supplying `full_name`, `email`, `phone`, and a residential `address` on or near the block. The new record starts with `standing` set to `GOOD` and a `forfeiture_count` of zero. Standing is the platform's memory of broken trust: each deposit forfeiture increments `forfeiture_count` by one, the first forfeiture demotes `standing` from `GOOD` to `FLAGGED`, and the second demotes it from `FLAGGED` to `SUSPENDED`, at which point the organizer can no longer open petitions or applications — attempts are rejected with `ERR_ORGANIZER_SUSPENDED`. For test-driving purposes, a `CityAdmin` can apply exactly one such forfeiture demotion directly to an organizer identified by `organizer_id`, without running a full event lifecycle.

Separately, a `CityAdmin` registers each closable **StreetSegment** with a human label `name` (for example, "Maple Ave 100-block"), a `jurisdiction` of `CITY`, `COUNTY`, or `STATE_ROUTE`, a `segment_kind` of `RESIDENTIAL` or `MIXED_USE`, the `household_count` of homes fronting the segment (zero or more), an optional `business_count` of business frontages (defaulting to 0, also zero or more), an optional `intersects_arterial` flag (defaulting to false) recording whether the closure touches an arterial intersection, and the segment's `length_m` in metres, which must be greater than zero. Jurisdiction drives the permit lead time, segment kind drives the petition threshold formula, and the arterial flag drives the barricade minimum — consequences developed in the following subsections.

### 3.2. The Petition: Thresholds, Signatures, and the Cure Loop

An organizer opens a **Petition** by naming the `segment_id` it covers; the platform stamps the petition with the creating caller as `organizer_id`, sets its `status` to `COLLECTING`, and freezes two computed attributes at creation time. The first is `support_mode`: for a `RESIDENTIAL` segment the mode is `DISTINCT_HOUSEHOLD`, and for a `MIXED_USE` segment it is `SIGNATURE_COUNT`. The second is `required_signatures`: on a `RESIDENTIAL` segment the threshold is 60 percent of the segment's `household_count` rounded up to a whole number, while on a `MIXED_USE` segment it is 60 percent of `household_count` plus 50 percent of `business_count`, the sum rounded up to a whole number. Either way the threshold never falls below one — a segment with no households and no businesses still requires a single signature.

Neighbors sign a petition by providing their `household_address`, `signer_name`, and `signer_email`, plus an optional `is_business` flag (defaulting to false) marking a business frontage. Signatures are accepted only while the petition is `COLLECTING`; attempts against a petition in any other state are rejected as a state violation, and once a petition is `LOCKED` the rejection carries `ERR_PETITION_LOCKED`. Each new signature starts `ACTIVE` with `withdrawn_at` absent, and the pair of `household_address` and `signer_email` must be unique among the petition's `ACTIVE` signatures — a repeat pairing is refused with `ERR_DUPLICATE_SIGNATURE`. Every accepted or withdrawn signature recomputes the petition's two counters, both of which start at zero and exclude `WITHDRAWN` rows entirely: `valid_signature_count`, the number of `ACTIVE` signature rows, and `distinct_household_count`, the number of distinct `household_address` values among them.

The petition's support metric depends on the pinned mode. Under `DISTINCT_HOUSEHOLD` the metric is `distinct_household_count`, so two active signatures from the same address count once. Under `SIGNATURE_COUNT` the metric is `valid_signature_count`, so the same two rows count twice — the modes deliberately diverge on identical signature sets. The threshold is satisfied when the applicable metric reaches `required_signatures`; exact equality passes.

When the organizer believes the threshold is met, submitting the petition moves it from `COLLECTING` to `SUBMITTED` — submitting from any other state is rejected with `ERR_INVALID_STATE` — and the metric is checked at that moment, falling short yielding `ERR_SIGNATURE_THRESHOLD_NOT_MET`. A `PermitOfficer` then adjudicates with a `decision` and an optional `note`. An `APPROVE` decision re-checks the metric against the threshold at verification time — signatures withdrawn since submission can sink a petition here, again surfacing `ERR_SIGNATURE_THRESHOLD_NOT_MET` — and on success moves the petition to `VERIFIED`; as a cascade, every permit application built on this petition that is currently `SUSPENDED` returns to `UNDER_REVIEW`. A `DEFICIENT` decision instead parks the petition in `DEFICIENT` with the supplied `note` recorded as `deficiency_note`, a field that stays absent until the first deficiency. The organizer may then cure the petition, which returns it from `DEFICIENT` to `COLLECTING` — curing from any other state fails with `ERR_INVALID_STATE` — and increments `cure_round`, which counts these deficiency cycles starting from zero.

Signatures can also be withdrawn. A neighbor withdraws an `ACTIVE` signature — withdrawing one already `WITHDRAWN` fails with `ERR_INVALID_STATE` — by addressing it through its `signatureId`; the petition must be `COLLECTING`, `SUBMITTED`, or `VERIFIED` at the time, and a withdrawal against a `LOCKED` petition is rejected with `ERR_PETITION_LOCKED`. Withdrawal stamps the signature `WITHDRAWN`, records `withdrawn_at` from the logical clock, and recomputes both counters. If the petition was `VERIFIED` and the withdrawal drops the applicable metric below `required_signatures`, the petition automatically collapses to `DEFICIENT` with `deficiency_note` set to "signature withdrawal below threshold", and — the cascade that makes the petition the backbone of the whole program — every linked application in `UNDER_REVIEW` or `APPROVED` drops to `SUSPENDED` with `decision_reason` recorded as "petition deficient". Applications suspended in this way return to `UNDER_REVIEW` only when the petition is verified again, and those that had already reached `APPROVED` must be approved anew.

Finally, the petition locks: the moment any application referencing it is issued, the petition transitions from `VERIFIED` to its terminal `LOCKED` state, from which neither signature creation nor withdrawal is possible. Listing a petition's signatures accepts an optional `status` filter, and the organizer and officers can list the applications backed by a petition to observe these linkages.

### 3.3. Drafting and Submitting the Permit Application

With a petition underway, the organizer drafts a **PermitApplication** by naming the backing `petition_id` and supplying the closure window `event_start_at` and `event_end_at` (ISO 8601 UTC; the closure may cross midnight, but the window must be strictly longer than zero and no longer than 12 hours, violations surfacing as `ERR_EVENT_WINDOW_INVALID`), the `expected_attendance` (greater than zero), and three optional booleans — `amplified_sound`, `alcohol_served`, and `food_vendors`, each defaulting to false. Serving alcohol blocks insurance waivers and raises both fee and deposit; outside food vendors are simply recorded and impose no extra gate. The backing petition must be in one of `COLLECTING`, `SUBMITTED`, `VERIFIED`, or `DEFICIENT` — never `LOCKED` — and must belong to the caller, with `ERR_NOT_RESOURCE_OWNER` greeting a petition owned by someone else and `ERR_ORGANIZER_SUSPENDED` a suspended caller. The application opens in `DRAFT`, stamped with the caller as `organizer_id`, and its `segment_id` is copied from the petition's segment at creation and denormalized onto the application precisely so that window-conflict checks can run without chasing the petition.

While the application remains `DRAFT` the organizer may revise it, replacing any of `event_start_at`, `event_end_at`, `expected_attendance`, `amplified_sound`, `alcohol_served`, or `food_vendors`. This update is one of the platform's two OCC-guarded writes: it requires `expected_application_version` matching the application's current `version`, succeeds by incrementing `version` by one, and otherwise fails with `ERR_STALE_APPLICATION_VERSION`. The `decision_reason` field stays empty at this stage — it is written only on denial, revocation, cancellation, or automatic suspension.

Submitting the application is the point of no return from `DRAFT` to `UNDER_REVIEW`, and three gates guard it. First, the backing petition must be `VERIFIED` (else `ERR_PETITION_NOT_VERIFIED`). Second, jurisdiction lead time: the event must start no sooner than the required notice period measured from the logical clock — 14 days for a `CITY` segment, 28 days for `COUNTY`, and 45 days for `STATE_ROUTE` — with an event starting exactly at the deadline passing, and anything earlier rejected as `ERR_LEAD_TIME_INSUFFICIENT`. Third, the segment window conflict check: application windows are half-open, and the new application conflicts with an existing one on the same segment when that application's `status` is `UNDER_REVIEW`, `SUSPENDED`, `APPROVED`, or `ISSUED` and the windows genuinely overlap — the existing event starts before the new one ends and the new one starts before the existing one ends. Mere adjacency is not a conflict: an event starting exactly when another ends (or ending exactly when another starts) passes. The application under submission is naturally excluded from its own comparison set. A conflict is rejected with `ERR_SEGMENT_WINDOW_CONFLICT`.

On successful submission the platform freezes `provisional_fee_cents`, an estimate computed from the application's fields as they stand at that moment. The fee subtotal starts from a base of 5000 cents ($50.00), adds an attendance tier — nothing when `expected_attendance` is 50 or fewer, 4000 cents when it falls between 51 and 150 inclusive, and 9000 cents when it exceeds 150 — adds 7500 cents when `alcohol_served` is true, adds 2500 cents when `amplified_sound` is true, and adds 10000 cents when the segment's `jurisdiction` is `STATE_ROUTE`. To this the estimate adds an equipment allowance: if a traffic control plan exists for the application — in any status — its current counts at submit time are priced at 250 cents per barricade, 25 cents per cone, and 100 cents per sign; with no plan, the allowance is zero. The provisional figure is deliberately plain: it never includes tax, never includes the large-event discount, and never includes the administrative surcharge. Permit officers browsing their review queue can filter the application list by `status` and `organizer_id`, paged through `limit` and `offset`.

### 3.4. The Review Lanes: Traffic Control, Amplified Sound, and Insurance

Three singleton children carry the application's compliance burden, each created at most once per application — a second create is refused with `ERR_DUPLICATE_RESOURCE` — and each retrievable as a list containing zero or one entry.

**Traffic control.** The organizer drafts the TrafficControlPlan — each of these lane children is stamped with the `application_id` of the application it belongs to — with `barricade_count`, `cone_count`, and `sign_count` (each zero or more), the `emergency_lane_width_m`, the `emergency_lane_continuous` flag, and free-text `placement_notes`. Creation is permitted while the application is `DRAFT`, `UNDER_REVIEW`, or `SUSPENDED` — drafting early matters, because the provisional fee prices the plan's counts at submit time — and the plan starts in `DRAFT`. While the plan is `DRAFT` or `CHANGES_REQUESTED` the organizer may revise any of those six fields, each revision incrementing the plan's `version`. Submitting the plan — from either `DRAFT` or `CHANGES_REQUESTED`, with identical validations — requires the application to be `UNDER_REVIEW` or `SUSPENDED` (else `ERR_INVALID_STATE`) and enforces two safety rules: the emergency lane must be continuous end-to-end for the full closure with `emergency_lane_width_m` of at least 6.0 metres (exactly 6.0 passes; violations raise `ERR_EMERGENCY_LANE_VIOLATION`), and `barricade_count` must reach the segment minimum — the segment's `length_m` divided by 12 and rounded up to a whole number, plus 4 additional barricades when the segment `intersects_arterial` (shortfalls raise `ERR_BARRICADE_PLAN_INSUFFICIENT`). A `TrafficReviewer` then adjudicates with a `decision`: `APPROVE` moves the plan to `TCP_APPROVED`, `REQUEST_CHANGES` returns it to `CHANGES_REQUESTED`, and either way the reviewer is recorded as `reviewed_by` with the supplied `note` stored in `review_note` (both fields remain empty until the first review). At permit issuance an approved plan locks: `TCP_APPROVED` becomes terminal `LOCKED`, and `locked_at_version` pins the plan's `version` at that instant — a field that stays empty until then.

**Amplified sound.** A SoundPlan may be created only when the application's `amplified_sound` is true — creating one for a quiet event is rejected with `ERR_SOUND_NOT_REQUESTED` — and only while the application is `UNDER_REVIEW` or `SUSPENDED`. The organizer declares `speaker_count` (greater than zero), `max_db_at_property_line` (greater than zero), and `planned_sound_end`. Submitting — again from `DRAFT` or `CHANGES_REQUESTED` under the same validations, with the application state gate of `UNDER_REVIEW` or `SUSPENDED` — enforces, in this order: first the decibel cap, where a declared level above 70 dB at the nearest property line is rejected with `ERR_SOUND_DB_EXCEEDED` (exactly 70 passes); then the day-of-week cutoff, where amplified sound must end by 22:00 when the day of `event_start_at` falls on a Friday or Saturday and by 21:00 on any other day, with a planned end exactly at the cutoff passing and anything later rejected with `ERR_SOUND_CUTOFF_VIOLATION`. A `SafetyReviewer` adjudicates: `APPROVE` moves the plan to `SOUND_APPROVED`, `REQUEST_CHANGES` returns it to `CHANGES_REQUESTED`, recording `reviewed_by` and `review_note` in either case. Like the traffic plan, an approved sound plan locks at issuance, pinning `locked_at_version` to its then-current `version`.

**Insurance.** The organizer files an InsuranceCertificate whose `kind` is either `CERTIFICATE` or `WAIVER_REQUEST`, while the application is `UNDER_REVIEW`, `SUSPENDED`, or `APPROVED` (else `ERR_INVALID_STATE`); if the application already holds a `VERIFIED` or `WAIVER_GRANTED` record, insurance is settled and any further create is rejected with `ERR_INVALID_STATE`. A `CERTIFICATE` filing requires `insurer_name`, `policy_number`, `coverage_amount_cents`, and `expires_on`; a `WAIVER_REQUEST` needs none of those. Creation is the platform's second OCC-guarded write, requiring `expected_application_version` matching the application's current `version` and failing staleness with `ERR_STALE_APPLICATION_VERSION` (HTTP 412). A successful create starts the new record at `SUBMITTED`, supersedes every prior record still sitting in `SUBMITTED`, `REJECTED`, or `WAIVER_DENIED` — each such record moves to `SUPERSEDED` with `superseded_by_id` pointing at the newer record (the pointer stays empty on any record that was never superseded) — and increments the application's `version` by one, which is exactly why a stale read of the application is dangerous here. A `SafetyReviewer` adjudicates with a `decision` and optional `note`. Approving a `CERTIFICATE` demands `coverage_amount_cents` of at least 100000000 cents — one million dollars of liability coverage, with shortfalls rejected as `ERR_INSURANCE_COVERAGE_INSUFFICIENT` — and an `expires_on` on or after the event's calendar date, with an earlier expiry rejected as `ERR_INSURANCE_EXPIRED`; success marks the record `VERIFIED`. Approving a `WAIVER_REQUEST` demands waiver eligibility — `expected_attendance` of at most 75, no alcohol service, and a `RESIDENTIAL` segment — with anything less qualifying rejected as `ERR_WAIVER_INELIGIBLE`; success marks the record `WAIVER_GRANTED`. Denial marks a certificate filing `REJECTED` or a waiver filing `WAIVER_DENIED`, storing the `note` in `review_note`. Every review outcome records the reviewer in `reviewed_by`, empty until then.

### 3.5. Approval, Issuance, and the Two Fee Schedules

Approval is a `PermitOfficer`'s act on an application in `UNDER_REVIEW`, and its checks fire in a fixed sequence. The petition is confirmed `VERIFIED` (else `ERR_PETITION_NOT_VERIFIED`); the traffic plan must exist in `TCP_APPROVED` (else `ERR_TCP_NOT_APPROVED`); when `amplified_sound` is true the sound plan must exist in `SOUND_APPROVED` (else `ERR_SOUND_PLAN_NOT_APPROVED`); insurance must be satisfied by a non-superseded record in `VERIFIED` or `WAIVER_GRANTED` (else `ERR_INSURANCE_NOT_SATISFIED`); equipment coverage must hold — for each kind `BARRICADE`, `CONE`, and `SIGN`, the sum of `units` across this application's reservations in `HELD` or `CONFIRMED` must reach the traffic plan's planned count for that kind (else `ERR_EQUIPMENT_NOT_RESERVED`); and a deposit must exist in `HELD` (else `ERR_DEPOSIT_REQUIRED`). All six green moves the application to `APPROVED`.

Issuance converts approval into a live permit. The officer re-verifies the petition — still `VERIFIED`, else `ERR_PETITION_NOT_VERIFIED` — and re-runs the segment window conflict check against the same half-open overlap rule used at submit, else `ERR_SEGMENT_WINDOW_CONFLICT`. Issuance then fans out: the application becomes `ISSUED` and its `version` increments by one; the backing petition locks from `VERIFIED` to `LOCKED`; the traffic plan locks from `TCP_APPROVED` to `LOCKED` and the sound plan from `SOUND_APPROVED` to `LOCKED`, each pinning `locked_at_version`; and every reservation still `HELD` is confirmed — `reservation_status` becomes `CONFIRMED` while its `billing_status` moves from `UNBILLED` to `INVOICED` with `invoice_cents` computed per line. That per-line computation is pinned: for each reservation line the pretax amount is `units` multiplied by the kind's unit rate (250 cents per barricade, 25 per cone, 100 per sign), the line's tax is that pretax amount multiplied by 8.25 percent and rounded half up to whole cents, and `invoice_cents` is pretax plus tax. Tax is rounded per line and only then summed — the alternative order of summing pretax across lines and taxing the total once is expressly rejected, because the two orders diverge by cents on common unit mixes. The application's `equipment_total_cents` is the sum of these per-line invoices, empty until issuance.

Issuance also freezes `final_fee_cents`, computed in a pinned evaluation order. First, the fee subtotal is recomputed with exactly the same tiered formula as the provisional fee — base 5000 cents, the attendance tier, the alcohol and sound add-ons, the state-route surcharge — but read from the application's current fields at issue time, which may have drifted from submit-time values. Second, the deposit requirement for this application is computed (per §3.7) and used only for discount eligibility. Third, the large-event test: if the fee subtotal plus that deposit requirement exceeds 20000 cents — evaluated strictly, on the pre-discount subtotal — the fee is discounted by ten percent, the product rounded half up to whole cents; otherwise the fee stands undiscounted. Fourth, an administrative surcharge of three percent of the discounted fee, rounded half up, is added — the surcharge applies to the fee alone, never to equipment or the deposit. Fifth, the equipment total from the lines just confirmed is taken. Sixth and finally, `final_fee_cents` is the discounted fee plus the surcharge plus `equipment_total_cents`. The provisional and final figures therefore answer different questions — an estimate without discount, surcharge, or tax at submit, versus the true invoice at issue — and the two diverge whenever discount, surcharge, or tax applies.

An officer may instead deny an application under review, supplying a `reason`. Denial moves the application from `UNDER_REVIEW` to terminal `DENIED` with `decision_reason` set, and unwinds everything the application had assembled: each `HELD` reservation is cancelled, releasing its stock reservation; a deposit still `HELD` auto-settles to `SETTLED` with `refund_cents` equal to `held_cents` minus `charges_cents`; and a pool in `OPEN` or `FUNDED` runs the refund chain of §3.7 to `REFUNDED`.

### 3.6. Equipment Logistics: Stock Selection, Dispatch, and Return

The depot side begins with `CityAdmin` registering each EquipmentStock — a `depot_name`, an `equipment_kind` of `BARRICADE`, `CONE`, or `SIGN`, and `total_units` greater than zero — starting life with `reserved_units` and `out_units` at zero and `available_units` equal to `total_units`. Anyone reviewing logistics can list stocks, optionally filtered by `equipment_kind`, and read a stock's counters, which are always computed against the logical clock.

An organizer reserves equipment by naming the `equipment_kind` and the `units` wanted (greater than zero) while the application is `UNDER_REVIEW`, `SUSPENDED`, or `APPROVED` — otherwise `ERR_INVALID_STATE`. The organizer never picks a depot; the server selects the stock. The selection considers the requesting application's buffered window — from 24 hours before `event_start_at` through 24 hours after `event_end_at`, both endpoints included — and computes, for every stock of the requested kind, its window-available units: `total_units` minus the units committed by that stock's reservations in `HELD`, `CONFIRMED`, or `DISPATCHED` whose own applications' buffered windows overlap the requested one. Overlap is closed — two windows overlap whenever each starts no later than the other ends, so windows that merely touch at an endpoint still overlap. Stocks whose window-available units meet or exceed the requested `units` are candidates; the selector ranks candidates by window-available units descending and breaks ties by the stock's `created_at` ascending, never by `id`. An empty candidate set rejects the reservation with `ERR_EQUIPMENT_UNAVAILABLE`. A created reservation opens with `reservation_status` `HELD` and `billing_status` `UNBILLED`, its `stock_id` recording the selector's choice, and its billing fields — `invoice_cents`, `dispatched_by`, `dispatched_at`, `return_due_at`, `returned_at`, `returned_units`, `late_days`, `return_verified_by` — empty until the corresponding lifecycle event fills them.

The two statuses of a reservation are independent dimensions: `reservation_status` tracks the physical lifecycle (`HELD`, `CONFIRMED`, `DISPATCHED`, `RETURNED`, and the terminals `CLOSED`, `CANCELLED`, `RECALLED`), while `billing_status` tracks money (`UNBILLED`, `INVOICED`, `PAID`, `WAIVED`). Before issuance the organizer may cancel a `HELD` reservation while the application is `UNDER_REVIEW`, `SUSPENDED`, or `APPROVED`, which moves it to `CANCELLED` and releases its stock reservation. After issuance, money moves first: the organizer pays an `INVOICED` reservation — payment is simulated — taking billing to `PAID`; alternatively a `PermitOfficer` may waive an invoice of at most 500 cents (an invoice of exactly 500 cents qualifies; anything larger fails with `ERR_WAIVER_AMOUNT_TOO_LARGE`), taking billing to `WAIVED`. The system itself waives invoiced billing automatically when a confirmed reservation is cancelled or recalled.

Physical movement belongs to depot officers, under segregation of duties. A `DepotOfficer` dispatches a `CONFIRMED` reservation only while the parent application is `ISSUED` (else `ERR_INVALID_STATE`) and only inside the dispatch window — from 48 hours before `event_start_at` through `event_start_at` itself, both endpoints included, with attempts outside rejected as `ERR_DISPATCH_WINDOW_VIOLATION`. Dispatch records `dispatched_by` from the officer's `X-User-ID`, stamps `dispatched_at` from the logical clock, fixes `return_due_at` at 48 hours after `event_end_at`, and moves the reserved `units` into the stock's out tally.

Recording the return takes the reservation from `DISPATCHED` to `RETURNED`. The officer reports `returned_units`, which must lie between zero and the reserved `units` inclusive — anything else is `ERR_INVALID_REQUEST`. The platform stamps `returned_at`, computes `late_days` — zero when the return lands at or before `return_due_at` (a return exactly at the deadline is on time), otherwise the hours late divided by 24 rounded up to whole days — and subtracts the returned quantity from the stock's out tally. Charges then post, but only while the application's deposit is still `HELD`. A late return posts a `LATE_EQUIPMENT` ChargeEntry of `returned_units` times the kind's unit rate times two, times `late_days`, written only when positive. A shortfall posts a `SHORTAGE` entry of the missing units — `units` minus `returned_units` — times the kind's rate times five, likewise only when positive. Every ChargeEntry carries its parent `deposit_id`, its `kind`, an `amount_cents` greater than zero, an explanatory `note`, and — for `LATE_EQUIPMENT` and `SHORTAGE` — the `source_reservation_id` of the reservation that caused it (empty for `CLEANING` charges). Should posted charges push the deposit's `charges_cents` to meet or exceed its `held_cents`, the deposit forfeits on the spot: `HELD` becomes `FORFEITED` with `refund_cents` zeroed, and the organizer's standing takes the demotion described in §3.1.

Closure of the loop requires a second pair of eyes. Verifying a return — moving the reservation from `RETURNED` to terminal `CLOSED` — must be performed by a `DepotOfficer` whose `X-User-ID` differs from the `dispatched_by` recorded at dispatch, segregation failures surfacing as `ERR_SOD_SAME_OFFICER` (HTTP 403), and billing must already be settled — `PAID` or `WAIVED`, since an outstanding `INVOICED` balance fails with `ERR_BILLING_UNSETTLED`. Verification records `return_verified_by`.

### 3.7. The Shared-Cost Pool and the Refundable Deposit

Block parties split costs. While the application is `UNDER_REVIEW`, `SUSPENDED`, `APPROVED`, or `ISSUED`, the organizer may open the singleton CostSharePool with a `target_cents` greater than zero; the pool starts `OPEN` with `collected_cents` and `refunded_cents` at zero. Neighbors contribute by naming their `household_address` and an `amount_cents` of at least 100 cents — smaller offerings are refused with `ERR_CONTRIBUTION_BELOW_MIN` — and only into an `OPEN` pool, contributions against any other state failing with `ERR_POOL_NOT_OPEN`. Each contribution is stamped `PAID` with `refunded_at` empty, its `pool_id` tying it to the pool, and the pool's `collected_cents` grows by the amount; the moment the running total reaches or exceeds `target_cents` — equality funds — the pool flips to `FUNDED`. After the event the organizer closes an `OPEN` or `FUNDED` pool, provided the application is `ISSUED` and the logical clock has passed `event_end_at` (else `ERR_INVALID_STATE`); a closed pool keeps its collections and no refunds flow.

The refund chain runs the other way when the underlying application dies. On the application becoming `CANCELLED`, `REVOKED`, `DENIED`, or `EXPIRED`, a pool in `OPEN` or `FUNDED` enters `REFUNDING`; every `PAID` contribution flips to `REFUNDED` with `refunded_at` stamped from the logical clock, the pool's `refunded_cents` accumulating each amount while `collected_cents` shrinks by the same; and once no `PAID` contributions remain the pool settles into terminal `REFUNDED` — all within the same request that triggered the chain.

The deposit is the program's enforcement instrument. The organizer creates the singleton Deposit while the application is `UNDER_REVIEW`, `SUSPENDED`, or `APPROVED`. Its `required_cents` are computed at creation from the application's fields: a base of 10000 cents, plus 15000 cents when `expected_attendance` exceeds 150, plus 20000 cents when `alcohol_served` is true. Payment is simulated, so `held_cents` simply equals `required_cents`, `status` opens at `HELD`, `charges_cents` starts at zero, and `refund_cents` stays empty until settlement. A `PermitOfficer` settles a held deposit manually once the application is `ISSUED` or `REVOKED` and the logical clock has passed `event_end_at` (any other state fails with `ERR_INVALID_STATE`), provided `charges_cents` remains below `held_cents` — at or above that line the deposit would already have forfeited automatically. Settlement moves it to `SETTLED` and pays `refund_cents` of `held_cents` minus `charges_cents`. The same auto-settlement fires without officer involvement when the application is cancelled, revoked, denied, or expired. Forfeiture is the mirror: the instant any posted charge makes `charges_cents` reach or exceed `held_cents`, the deposit flips to `FORFEITED` with `refund_cents` of zero, the organizer's `forfeiture_count` increments, and `standing` demotes — `GOOD` to `FLAGGED` on the first lifetime forfeiture, `FLAGGED` to `SUSPENDED` on the second. Anyone entitled may list the charge entries posted against a deposit to audit how the balance eroded.

### 3.8. Cleanup Reporting, Inspection, and Event Completion

Once the street reopens, accountability lands on the organizer. While the application is `ISSUED`, the organizer files the singleton PostEventReport attesting `cleanup_completed` with free-text `cleanup_notes`; the filing must land after `event_end_at` and no later than 72 hours after it — the window is open at the start (a report exactly at `event_end_at` is too early) and closed at the end (a report exactly 72 hours after is still inside) — with violations rejected as `ERR_REPORT_WINDOW_CLOSED`. The report stamps `submitted_at` from the logical clock and opens with `inspection_result` `PENDING` and `cleaning_charge_cents` at zero.

A `PermitOfficer` then inspects, supplying a `result` and, on failure, an optional `cleaning_charge_cents` defaulting to 0. A `PASSED` result records `inspected_by` and closes the report. A `FAILED` result records `inspected_by`, stores the supplied `cleaning_charge_cents`, and — when that figure is positive and the application's deposit is still `HELD` — posts a `CLEANING` ChargeEntry against the deposit. Should that charge push the deposit's charges to meet or exceed the held amount, the deposit forfeits exactly as in §3.6, and the organizer's standing demotes accordingly.

Completion is the permit office's final gate on an `ISSUED` application, and every condition must hold: the logical clock has passed `event_end_at`; the latest post-event report's `inspection_result` is `PASSED`; every equipment reservation stands in a terminal state — `CLOSED`, `CANCELLED`, or `RECALLED`; the deposit, if one exists, is `SETTLED` or `FORFEITED`; and the cost-share pool, if one exists, is `CLOSED` or `REFUNDED`. Any shortfall rejects the completion with `ERR_COMPLETION_PRECONDITIONS`; all five satisfied moves the application to terminal `COMPLETED`.

### 3.9. Cancellation, Revocation, and Lazy Expiry

Organizers may abandon an application almost anywhere in its lifecycle, supplying an optional `reason`, and the cascade depth depends on where it dies. From `DRAFT`, cancellation simply records `CANCELLED` with `decision_reason` — nothing downstream exists yet. From `UNDER_REVIEW`, `SUSPENDED`, or `APPROVED`, cancellation additionally unwinds the application's commitments: each `HELD` reservation becomes `CANCELLED` and releases its stock reservation; a `HELD` deposit auto-settles to `SETTLED` with `refund_cents` equal to `held_cents` minus `charges_cents`; and an `OPEN` or `FUNDED` pool runs the refund chain to `REFUNDED`. From `ISSUED`, cancellation is permitted only when no reservation is still `DISPATCHED` — outstanding equipment must be returned first, and attempts otherwise fail with `ERR_INVALID_STATE` — and then each `CONFIRMED` reservation is cancelled, releasing its stock and automatically waiving any `INVOICED` billing, with the deposit auto-settling and the pool refunding as before.

Revocation is the officer's counterpart on an issued permit, requiring a `reason`. The same guard applies — no reservation may be `DISPATCHED`, else `ERR_INVALID_STATE` — and on success the application becomes terminal `REVOKED` with `decision_reason` recorded, each `CONFIRMED` reservation moves to `RECALLED` with its stock reservation released and its invoiced billing waived, the deposit auto-settles, and the pool runs its refund chain. The petition, notably, stays `LOCKED` through revocation: the neighborhood's consent was consumed at issuance and is not refunded.

Finally, applications can simply rot. On any access to an application whose `event_end_at` has passed on the logical clock, a status of `DRAFT`, `UNDER_REVIEW`, `SUSPENDED`, or `APPROVED` lazily collapses to terminal `EXPIRED`, with the same unwind as a pre-issuance cancellation — held reservations cancelled and released, the deposit auto-settled, the pool refunded. An application that reached `ISSUED` never expires this way; it must be completed, cancelled, or revoked on its merits.

## 4. Endpoint Definitions

Operations that create a new resource — whether a top-level record or a new child in a collection — return `201 Created`. Operations that modify an existing resource or drive a state transition return `200 OK`. All responses use the envelope of §2.2, and all requests are subject to the validation order of §2.6.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/organizers` | Register an organizer | Anonymous |
| GET | `/organizers/{id}` | Get an organizer | Organizer, PermitOfficer, CityAdmin |
| GET | `/organizers/{id}/petitions` | List petitions created by an organizer | Organizer, PermitOfficer, CityAdmin |
| GET | `/organizers/{id}/permit-applications` | List permit applications created by an organizer | Organizer, PermitOfficer, CityAdmin |
| POST | `/_inject/organizer_forfeiture` | Test hook: apply one deposit-forfeiture demotion to an organizer (identified by `organizer_id`) | CityAdmin |
| POST | `/street-segments` | Register a street segment (city configuration) | CityAdmin |
| GET | `/street-segments/{id}` | Get a street segment | Organizer, Neighbor, TrafficReviewer, SafetyReviewer, PermitOfficer, DepotOfficer, CityAdmin |
| GET | `/street-segments/{id}/petitions` | List petitions for a segment | Organizer, Neighbor, TrafficReviewer, SafetyReviewer, PermitOfficer, DepotOfficer, CityAdmin |
| GET | `/street-segments/{id}/permit-applications` | List permit applications for a segment | Organizer, TrafficReviewer, SafetyReviewer, PermitOfficer, DepotOfficer, CityAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock | CityAdmin |
| POST | `/petitions` | Create a petition for a segment | Organizer |
| GET | `/petitions/{id}` | Get a petition | Organizer, Neighbor, PermitOfficer, CityAdmin |
| POST | `/petitions/{id}/signatures` | Add a signature to a collecting petition | Neighbor |
| GET | `/petitions/{id}/signatures` | List signatures of a petition | Organizer, Neighbor, PermitOfficer, CityAdmin |
| POST | `/petitions/{id}/signatures/{signatureId}/withdraw` | Withdraw an active signature | Neighbor |
| POST | `/petitions/{id}/submit` | Submit a petition for verification | Organizer |
| POST | `/petitions/{id}/verify` | Verify a petition or mark it deficient | PermitOfficer |
| POST | `/petitions/{id}/cure` | Re-open a deficient petition for more signatures | Organizer |
| GET | `/petitions/{id}/permit-applications` | List applications backed by this petition | Organizer, PermitOfficer, CityAdmin |
| POST | `/permit-applications` | Create a permit application | Organizer |
| GET | `/permit-applications` | List applications with filters and pagination | PermitOfficer, CityAdmin |
| GET | `/permit-applications/{id}` | Get an application (lazy expiry evaluated on access) | Organizer, TrafficReviewer, SafetyReviewer, PermitOfficer, DepotOfficer, CityAdmin |
| PATCH | `/permit-applications/{id}` | Update a draft application's fields (OCC-guarded) | Organizer |
| POST | `/permit-applications/{id}/submit` | Submit an application for review | Organizer |
| POST | `/permit-applications/{id}/approve` | Approve an application when all review lanes are green | PermitOfficer |
| POST | `/permit-applications/{id}/deny` | Deny an application under review | PermitOfficer |
| POST | `/permit-applications/{id}/issue` | Issue the permit: lock petition and plans, confirm reservations, compute final fee | PermitOfficer |
| POST | `/permit-applications/{id}/cancel` | Organizer cancels an application (cascades differ by state) | Organizer |
| POST | `/permit-applications/{id}/revoke` | Revoke an issued permit | PermitOfficer |
| POST | `/permit-applications/{id}/complete` | Close out an event after the post-event gates pass | PermitOfficer |
| POST | `/permit-applications/{id}/traffic-control-plans` | Create the traffic control plan (singleton) | Organizer |
| GET | `/permit-applications/{id}/traffic-control-plans` | List traffic control plans of an application (0 or 1) | Organizer, TrafficReviewer, PermitOfficer, CityAdmin |
| GET | `/traffic-control-plans/{id}` | Get a traffic control plan | Organizer, TrafficReviewer, PermitOfficer, CityAdmin |
| PATCH | `/traffic-control-plans/{id}` | Update a plan while DRAFT or CHANGES_REQUESTED | Organizer |
| POST | `/traffic-control-plans/{id}/submit` | Submit a plan for traffic review | Organizer |
| POST | `/traffic-control-plans/{id}/review` | Traffic reviewer decision (approve or request changes) | TrafficReviewer |
| POST | `/permit-applications/{id}/sound-plans` | Create a sound plan (only when amplified sound is requested) | Organizer |
| GET | `/permit-applications/{id}/sound-plans` | List sound plans of an application (0 or 1) | Organizer, SafetyReviewer, PermitOfficer, CityAdmin |
| GET | `/sound-plans/{id}` | Get a sound plan | Organizer, SafetyReviewer, PermitOfficer, CityAdmin |
| POST | `/sound-plans/{id}/submit` | Submit a sound plan for safety review | Organizer |
| POST | `/sound-plans/{id}/review` | Safety reviewer decision (approve or request changes) | SafetyReviewer |
| POST | `/permit-applications/{id}/insurance-certificates` | Create an insurance record (certificate or waiver request; OCC-guarded; supersedes prior unresolved records) | Organizer |
| GET | `/permit-applications/{id}/insurance-certificates` | List insurance records of an application | Organizer, SafetyReviewer, PermitOfficer, CityAdmin |
| GET | `/insurance-certificates/{id}` | Get an insurance record | Organizer, SafetyReviewer, PermitOfficer, CityAdmin |
| POST | `/insurance-certificates/{id}/review` | Safety reviewer decision with coverage, expiry, and waiver-eligibility checks | SafetyReviewer |
| POST | `/equipment-stocks` | Register depot equipment stock | CityAdmin |
| GET | `/equipment-stocks` | List stocks (optional kind filter) | Organizer, TrafficReviewer, SafetyReviewer, PermitOfficer, DepotOfficer, CityAdmin |
| GET | `/equipment-stocks/{id}` | Get a stock (counters computed against the logical clock) | Organizer, TrafficReviewer, SafetyReviewer, PermitOfficer, DepotOfficer, CityAdmin |
| GET | `/equipment-stocks/{id}/equipment-reservations` | List reservations drawn on a stock | PermitOfficer, DepotOfficer, CityAdmin |
| POST | `/permit-applications/{id}/equipment-reservations` | Reserve equipment (server selects the stock) | Organizer |
| GET | `/permit-applications/{id}/equipment-reservations` | List reservations of an application | Organizer, PermitOfficer, DepotOfficer, CityAdmin |
| GET | `/equipment-reservations/{id}` | Get a reservation | Organizer, PermitOfficer, DepotOfficer, CityAdmin |
| POST | `/equipment-reservations/{id}/cancel` | Cancel a held reservation (pre-issuance only) | Organizer |
| POST | `/equipment-reservations/{id}/pay` | Pay an invoice (simulated) | Organizer |
| POST | `/equipment-reservations/{id}/waive` | Waive a small invoice (at most 500 cents) | PermitOfficer |
| POST | `/equipment-reservations/{id}/dispatch` | Dispatch equipment within the dispatch window | DepotOfficer |
| POST | `/equipment-reservations/{id}/return` | Record an equipment return; computes late days and posts charges | DepotOfficer |
| POST | `/equipment-reservations/{id}/verify-return` | Verify a return (different officer than the dispatcher; billing settled) | DepotOfficer |
| POST | `/permit-applications/{id}/cost-share-pools` | Create the shared-cost pool (singleton) | Organizer |
| GET | `/permit-applications/{id}/cost-share-pools` | List cost-share pools of an application (0 or 1) | Organizer, Neighbor, PermitOfficer, CityAdmin |
| GET | `/cost-share-pools/{id}` | Get a pool | Organizer, Neighbor, PermitOfficer, CityAdmin |
| POST | `/cost-share-pools/{id}/contributions` | Contribute to an open pool (payment simulated) | Neighbor |
| GET | `/cost-share-pools/{id}/contributions` | List contributions of a pool | Organizer, Neighbor, PermitOfficer, CityAdmin |
| POST | `/cost-share-pools/{id}/close` | Close a pool after the event (funds retained) | Organizer |
| POST | `/permit-applications/{id}/deposits` | Create and fund the refundable deposit (singleton) | Organizer |
| GET | `/permit-applications/{id}/deposits` | List deposits of an application (0 or 1) | Organizer, PermitOfficer, CityAdmin |
| GET | `/deposits/{id}` | Get a deposit | Organizer, PermitOfficer, CityAdmin |
| POST | `/deposits/{id}/settle` | Settle a deposit after the event (refund is held minus charges) | PermitOfficer |
| GET | `/deposits/{id}/charges` | List charge entries posted to a deposit | Organizer, PermitOfficer, CityAdmin |
| POST | `/permit-applications/{id}/post-event-reports` | Submit the cleanup report within the report window | Organizer |
| GET | `/permit-applications/{id}/post-event-reports` | List post-event reports of an application (0 or 1) | Organizer, PermitOfficer, CityAdmin |
| GET | `/post-event-reports/{id}` | Get a post-event report | Organizer, PermitOfficer, CityAdmin |
| POST | `/post-event-reports/{id}/inspect` | Inspect the report; failure may post a cleaning charge and forfeit the deposit | PermitOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error are described in the workflow narratives of §2 and §3; this catalogue is the index of identifiers and statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_ORGANIZER_SUSPENDED` | 403 Forbidden |
| `ERR_SOD_SAME_OFFICER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_EVENT_WINDOW_INVALID` | 400 Bad Request |
| `ERR_CONTRIBUTION_BELOW_MIN` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_DUPLICATE_RESOURCE` | 409 Conflict |
| `ERR_DUPLICATE_SIGNATURE` | 409 Conflict |
| `ERR_SIGNATURE_THRESHOLD_NOT_MET` | 409 Conflict |
| `ERR_PETITION_NOT_VERIFIED` | 409 Conflict |
| `ERR_PETITION_LOCKED` | 409 Conflict |
| `ERR_SEGMENT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_SOUND_NOT_REQUESTED` | 409 Conflict |
| `ERR_INSURANCE_NOT_SATISFIED` | 409 Conflict |
| `ERR_EQUIPMENT_UNAVAILABLE` | 409 Conflict |
| `ERR_BILLING_UNSETTLED` | 409 Conflict |
| `ERR_POOL_NOT_OPEN` | 409 Conflict |
| `ERR_DEPOSIT_REQUIRED` | 409 Conflict |
| `ERR_TCP_NOT_APPROVED` | 409 Conflict |
| `ERR_SOUND_PLAN_NOT_APPROVED` | 409 Conflict |
| `ERR_EQUIPMENT_NOT_RESERVED` | 409 Conflict |
| `ERR_COMPLETION_PRECONDITIONS` | 409 Conflict |
| `ERR_STALE_APPLICATION_VERSION` | 412 Precondition Failed |
| `ERR_LEAD_TIME_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_EMERGENCY_LANE_VIOLATION` | 422 Unprocessable Entity |
| `ERR_BARRICADE_PLAN_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_SOUND_DB_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SOUND_CUTOFF_VIOLATION` | 422 Unprocessable Entity |
| `ERR_INSURANCE_COVERAGE_INSUFFICIENT` | 422 Unprocessable Entity |
| `ERR_INSURANCE_EXPIRED` | 422 Unprocessable Entity |
| `ERR_WAIVER_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_DISPATCH_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_WAIVER_AMOUNT_TOO_LARGE` | 422 Unprocessable Entity |
| `ERR_REPORT_WINDOW_CLOSED` | 422 Unprocessable Entity |
