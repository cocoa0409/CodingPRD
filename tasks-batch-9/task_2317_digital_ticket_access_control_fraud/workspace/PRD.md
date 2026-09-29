# Ticket Access Control API — Product Requirements Document

## 1. Introduction

Venue ticketing has become an adversarial business. A barcode that never changes is a barcode that can be screenshotted, forwarded to a group chat and presented at four different turnstiles; a resale market with no verified channel is a market where the same seat is sold three times over; and a gate crew that loses its network uplink at the worst possible moment still has to admit ten thousand people without breaching fire code. This document specifies the Ticket Access Control API, the server-side system that venue operations, box office staff, gate crews and fraud investigators all work through when they issue, transfer, resell, scan, deny and finally reconcile digital entitlements.

The design rests on three commitments. First, **every entitlement is bound to something harder to copy than an image** — a rotating barcode derived from a server-minted seed, plus a device fingerprint the holder registers before arriving. Second, **every denial is evidence**: a refused scan is not merely an error response but a persisted record that opens an investigation, moves a patron's risk score and can suspend that patron's live resale listings within the same request. Third, **head counts are never guesses**. The system tracks a live, network-authoritative occupancy figure used to enforce fire code at the turnstile, and a separate reconciled attendance figure that includes scans replayed from an offline scanner cache; the two deliberately disagree, and the post-event reconciliation report exists precisely to explain the gap against what venue operations reported.

Because these workflows are money-bearing and safety-bearing at the same time, the specification is unusually strict about evaluation order, boundary inclusivity and rounding. Where two plausible readings of a rule would produce different cents or a different denial code, this document pins one reading. Implementers should treat the ordering statements in §2.12 and the arithmetic in §2.9 through §2.11 as contractual rather than advisory.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide contract: authentication, response shape, pagination, time, identity, concurrency, arithmetic and the order in which rules fire. Domain workflows follow in §3.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. Six roles exist and their spelling is exact: `Patron`, `BoxOfficeAgent`, `TicketingApprover`, `GateOperator`, `SecurityInvestigator`, and `VenueAdmin`. A request missing either header, or carrying an `X-User-Role` value outside those six, is rejected with `ERR_UNAUTHENTICATED` (401). A request whose role is well-formed but is not listed among the authorized roles for the endpoint in §4 is rejected with `ERR_FORBIDDEN_ROLE` (403).

The roles are deliberately segregated. A `Patron` is the only role that acts on entitlements it holds — device binding, transfer offers and decisions, resale listing, purchase and delisting. A `BoxOfficeAgent` registers patrons, records identity checks, issues tickets directly and drafts and submits non-sale distributions. A `TicketingApprover` decides those distributions and may never decide one it submitted itself. A `GateOperator` opens and closes scan sessions, records live scans and uploads offline caches. A `SecurityInvestigator` adjudicates denied-entry incidents and voids compromised entitlements. A `VenueAdmin` configures events, access zones and gates, advances event status, cuts and finalizes reconciliation reports, and owns the logical clock.

Identity semantics differ by role, and this is what ties `X-User-ID` to ownership. When `X-User-Role` is `Patron`, `X-User-ID` is the `id` of the acting `Patron` record; ownership checks compare that value to the resource's patron-bearing field — `holder_patron_id` on the ticket for device binding, transfer creation and resale listing, `to_patron_id` on the request for a transfer acceptance, either `to_patron_id` or `from_patron_id` for a decline, and `seller_patron_id` on the listing for a delist. A mismatch is rejected with `ERR_NOT_TICKET_HOLDER` (403). When `X-User-Role` is `BoxOfficeAgent`, `TicketingApprover`, `GateOperator`, `SecurityInvestigator` or `VenueAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow calls for it — as `requested_by_user_id` on a submitted credential request, `approved_by_user_id` on an approved or rejected one, `reviewer_user_id` on an incident taken for review, `finalized_by_user_id` on a finalized reconciliation report, and `actor_user_id` on every audit entry — but never compares it to any entity's `id`.

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

List endpoints are paginated through two query parameters. `limit` caps the number of rows returned; it defaults to 10, its minimum accepted value is 1 and its maximum is 100. `offset` is the number of rows to skip and defaults to 0.

On every list endpoint, `data` is the JSON array of rows, and the four pagination fields sit beside `data` inside `meta`: a client reads `limit`, `offset`, `total_count` and `has_more` from `meta` while the rows themselves are the elements of `data`. `total_count` is the number of rows matching the supplied filters *before* `limit` and `offset` are applied, and `has_more` is true exactly when `offset` plus the number of returned rows is still less than `total_count`.

Unless a specific endpoint says otherwise, list results are sorted by `created_at` ascending. Two endpoints override that default: the scan-event list is ordered by `recorded_at` ascending with `created_at` ascending as the tie-break, and the event audit trail is ordered newest-first by `occurred_at` descending with `created_at` descending as the tie-break.

### 2.4. The Logical Clock

Nothing in this system is evaluated against wall-clock time. The server maintains a **logical clock**, and every deadline, barcode epoch, re-entry lockout, credential validity window and session interval is compared against it. Before any client has moved it, the logical clock reads exactly `2026-08-01T00:00:00Z`, and it never falls back to real time.

A `VenueAdmin` moves the clock through an admin-only test-driving capability that accepts a single `to_iso8601` instant and answers with the resulting `current_utc` alongside the `previous_utc` it replaced. Moving the clock mutates no entity; it simply changes the instant against which every time-dependent derivation is subsequently computed. Endpoints that record a server-side instant — `opened_at` and `closed_at` on a scan session, `recorded_at` on a scan event, `decided_at` on a transfer decision, `occurred_at` on an audit entry — take the logical clock's value at the moment of the write.

### 2.5. Common Resource Properties, Timestamps and Versioning

Every persisted resource carries an `id`, which is a server-minted UUID with no type prefix, and a `created_at`, an ISO 8601 UTC timestamp with three fractional digits recording when the row was first written. Most resources additionally carry an `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and a `version`, an integer that starts at 1 on creation and increments by one on every mutation of that resource. Recomputation of a derived field counts as a mutation: when a ticket void moves an access zone's `issued_entitlement_count` and `posture`, the zone's `updated_at` and `version` move with them.

Two record types are append-only and therefore carry neither `updated_at` nor `version`: the immutable scan event, and the audit log entry. Both expose only `id` and `created_at` on top of their domain fields.

Several version movements are called out explicitly because clients depend on them for concurrency control. Creating an event mints it at `version` 1; advancing its status increments it by one, and cutting a reconciliation report against it increments it by one. Creating a gate mints it at `version` 1; opening a scan session on it and closing that session each increment it by one. Recording an identity check on a patron increments the patron's `version` by one. Binding a device to a ticket, releasing that binding, accepting a transfer of it, listing it for resale and delisting it each increment the ticket's `version` by one.

### 2.6. Stale-Version Guards on Parent Aggregates

Three write operations create a child row against a parent whose state the client must have observed first. Each of them requires a non-optional version field in its request body, and each rejects a mismatch with its own error at HTTP 412. Endpoints not named here take no version field at all.

- Creating a resale listing (`POST /resale-listings`) must carry `expected_ticket_version` matching the target ticket's current `version`. If another writer has advanced the ticket's `version` since the client last read it — a device rebind, a completed transfer, an earlier listing or delist — the create is rejected with `ERR_STALE_TICKET_VERSION` (412). A relisting legitimately supersedes a prior `DELISTED` or `SUSPENDED` listing on the same ticket, so the write itself is valid product behaviour; the stale-version guard is what stops a client from listing on top of a ticket whose holder, binding or lifecycle has moved since it was read.
- Opening a scan session (`POST /scan-sessions`) must carry `expected_gate_version` matching the target gate's current `version`. A mismatch is rejected with `ERR_STALE_GATE_VERSION` (412). A new session legitimately succeeds the previous closed one on the same gate, so this guard is the only thing stopping an operator from opening a session against a stale view of the gate's lane configuration and session history.
- Cutting a reconciliation report (`POST /events/{id}/reconciliation-reports`) must carry `expected_event_version` matching the target event's current `version`. A mismatch is rejected with `ERR_STALE_EVENT_VERSION` (412). A later report legitimately supersedes an earlier `DRAFT` one, so the guard is what stops a report from being cut against out-of-date occupancy and settlement figures.

### 2.7. Reference Resolution and Same-Event Integrity

The API is a flat set of top-level collections linked by identifier fields rather than by deep URL nesting. Where a path does carry more than one identifier, the identifiers are resolved strictly left to right and the first one that fails to resolve determines the 404 returned. Each collection raises its own not-found error: `ERR_EVENT_NOT_FOUND`, `ERR_ZONE_NOT_FOUND`, `ERR_GATE_NOT_FOUND`, `ERR_PATRON_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_TRANSFER_NOT_FOUND`, `ERR_LISTING_NOT_FOUND`, `ERR_CREDENTIAL_REQUEST_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_SCAN_EVENT_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND` and `ERR_REPORT_NOT_FOUND`.

Identifier fields inside a request body are resolved on the same basis and raise the same collection-specific errors: `event_id`, `access_zone_id`, `holder_patron_id`, `to_patron_id`, `recipient_patron_id`, `gate_id` and `ticket_id`. Beyond mere existence, a referenced access zone or gate must belong to the *same* event as the resource being created or acted on; a cross-event reference is rejected with `ERR_CROSS_EVENT_REFERENCE` (422). This applies to direct ticket issuance, to gate creation, and to credential-request drafting.

### 2.8. Money, Rounding and Conservation

All monetary amounts in this system are integer counts of cents and are stored as integers — there are no fractional cents anywhere in a response body. Wherever a percentage is applied to a cent amount, the product is rounded to a whole cent using **round half up** before it is used in any further arithmetic. Where a formula has several percentage components, each component is rounded to whole cents *individually* and only then combined; rounding a summed percentage once is never correct. The single non-integer stored figure in the system is a reconciliation report's `variance_pct`, which is carried to exactly two decimal places, also rounded half up. Two configured fractions — a zone's `comp_discount_pct` and the report's variance tolerance — preserve their input precision and are not rounded.

Money is conserved. An event's `settlement_pool_cents` is the venue-held balance: paid direct issuance adds a ticket's `face_value_cents` to it, a completed resale adds the listing's `venue_royalty_cents` to it, a remediation payout subtracts the granted credit from it, and a refunding void subtracts the refunded face value from it. Whatever leaves the pool arrives somewhere: a remediation credit and a refunded void both land in the holder's `remediation_credit_cents`, and a resale seller's proceeds land in that patron's `payout_balance_cents`. Entitlements are conserved on the same principle: an event's `entitlements_outstanding` counts its tickets whose `lifecycle_status` is `ISSUED`, `LISTED`, `TRANSFERRED` or `RESOLD`, so issuance raises it by one and voiding lowers it by one, while transfers, listings, delistings and resales — which move a ticket *between* those four statuses — leave it untouched. A zone's `issued_entitlement_count` counts the same four statuses restricted to tickets of that zone.

### 2.9. Fire Code, Occupancy and Two Readings of Attendance

Fire code is enforced at two levels at once: each `AccessZone` carries its own `fire_code_capacity` and each `Event` carries a venue-wide `fire_code_capacity`. Both are ceilings on *live* occupancy, and both must have headroom for a scan to be admitted.

The same stream of scan events yields two different head counts, and the distinction is load-bearing.

The **live** reading, persisted as an event's `live_occupancy` and a zone's `occupancy_count`, replays only those scan events whose `source` is `ONLINE`, in ascending `recorded_at` order with ascending `created_at` as the tie-break. Each `ADMITTED` result adds one, each `EXIT_RECORDED` result subtracts one, and every denial result contributes nothing. The running figure is clamped at a floor of zero. This is the reading consulted by the capacity preconditions at the turnstile and by the occupancy read endpoint, which means an un-uploaded scanner cache is deliberately invisible to the fire-code gate. An event also keeps `peak_live_occupancy`, the highest value its `live_occupancy` has reached since the event was created, raised whenever the live figure exceeds it.

The **reconciled** reading, persisted as a report's `scan_derived_attendance` and surfaced as `reconciled_attendance` on the occupancy read, counts distinct `ticket_id` values across scan events whose `result` is `ADMITTED` regardless of `source`, so offline-replayed scans are included, processed in ascending `scanned_at` order with ascending `recorded_at` as the tie-break. Exits do not reduce this figure, because it measures attendance rather than presence. For an identical event the reconciled reading can therefore exceed the live one.

The occupancy read also projects how long the remaining queue will take to clear. Only gates whose `status` is `SCANNING` contribute throughput; an `IDLE` gate contributes nothing. Total capacity per minute is the sum, over scanning gates, of each gate's `throughput_per_minute` multiplied by its `lanes_open`. The waiting population is the number of the event's tickets whose `lifecycle_status` is `ISSUED`, `LISTED`, `TRANSFERRED` or `RESOLD` and whose `admission_status` is still `NOT_ADMITTED`. `projected_clearance_minutes` is the waiting population divided by the capacity per minute, rounded *up* to a whole minute; when no gate is scanning, and therefore capacity per minute is zero, `projected_clearance_minutes` is null rather than an error. Alongside it the read reports the event's `event_id`, `live_occupancy`, `peak_live_occupancy`, `reconciled_attendance`, `fire_code_capacity`, the `headroom` remaining (the event's fire-code capacity less its live occupancy), and a `zone_occupancy` array carrying, for each access zone of the event, that zone's `id`, `zone_code`, `occupancy_count` and `fire_code_capacity`.

### 2.10. Patron Fraud Risk Scoring

Each patron carries a persisted `fraud_risk_score` between 0 and 100 and a `fraud_risk_basis` recording which of two readings produced it, either `PROVISIONAL` or `ADJUDICATED`. A newly registered patron starts at a score of 0 on a `PROVISIONAL` basis.

The score is built from two ingredients. The first is device churn: a patron's `device_rebind_count` counts every time they have bound a device to a ticket *after* the first binding on that ticket, and churn contributes four points for each rebind beyond the first — formally, four multiplied by the greater of zero and one less than `device_rebind_count`. The second is the patron's denied-entry history, where each incident contributes points according to its `category`: `COUNTERFEIT` weighs 50, `DEVICE_MISMATCH` weighs 45, `UNAUTHORIZED_RESALE` weighs 30, `DUPLICATE` weighs 20 and `ZONE_VIOLATION` weighs 15.

The two readings differ only in how they treat adjudicated incidents. The `PROVISIONAL` reading — written the instant an incident is created, while nobody has yet reviewed it — adds the churn points to the full weight of every incident whose `status` is `OPEN`, `UNDER_REVIEW` or `REMEDIATED`. It is the strictest reading. The `ADJUDICATED` reading — written when an incident reaches `REMEDIATED` or `DISMISSED` — adds the churn points to the full weight of every `OPEN` or `UNDER_REVIEW` incident, plus, for each `REMEDIATED` incident, its category weight multiplied by 0.5 — that is, halved — and rounded half up to a whole point, and adds nothing at all for `DISMISSED` incidents, which drop out entirely. Under either reading the raw total is then capped at 100. A single `DEVICE_MISMATCH` incident therefore scores 45 provisionally and 23 once adjudicated.

The score gates commercial activity: creating a resale listing and creating a transfer request both require the acting patron's `fraud_risk_score` to be **strictly below 40**. A score of exactly 40 is blocked, with `ERR_PATRON_FRAUD_BLOCKED` (403).

### 2.11. The Rotating Barcode and Its Acceptance Window

A ticket's barcode is not a constant. Each event fixes a `barcode_anchor_at` instant, and time is divided from that anchor into 30-second epochs. The **epoch index** for an instant is the difference between that instant and the anchor, divided by 30 seconds and rounded down toward negative infinity, so instants before the anchor yield negative indices. A ticket's barcode at any instant is its server-minted `barcode_seed`, then a single hyphen, then the decimal epoch index for that instant. The barcode read endpoint returns the ticket's `ticket_id`, its `barcode_seed`, the `barcode_epoch_index` current at the logical clock, the assembled `current_barcode`, and the `accepted_epoch_floor`, which is one epoch below the current index.

Acceptance of a `presented_barcode` is evaluated before any other admission check, and the clauses are evaluated left to right so that the first failing clause decides the outcome. The presented string is split at its **last** hyphen into a seed part and an epoch part. If no ticket's `barcode_seed` equals the seed part, the scan is adjudicated `DENIED_COUNTERFEIT` and reported as `ERR_COUNTERFEIT_BARCODE`. If the epoch part is not a valid integer, the outcome is the same. Otherwise the server computes the epoch index of the logical clock; if the presented epoch part is greater than that index, or is smaller than that index minus one, the scan is adjudicated `DENIED_STALE_BARCODE` and reported as `ERR_BARCODE_EPOCH_INVALID`. The accepted window is exactly the closed integer range from one below the current index up to and including the current index — one epoch of skew tolerance, which is what makes a forwarded screenshot useless within a minute. Epoch indices are integers and instants are compared at whole-second resolution.

### 2.12. Rule Evaluation Order

When several rules could reject the same request, the lowest-numbered rule below wins and no later rule is evaluated. The ladder is global: a rule's position holds on every endpoint it guards.

1. Authentication headers present and the role recognized — `ERR_UNAUTHENTICATED` (401), all endpoints.
2. The acting role is authorized for the endpoint per §4 — `ERR_FORBIDDEN_ROLE` (403), all endpoints.
3. Request-body shape: every required field present, enum values inside their declared sets, integers inside their declared ranges, `valid_until` strictly after `valid_from`, and ISO-8601 timestamps parseable — `ERR_INVALID_REQUEST` (400), every endpoint that takes a body.
4. Path identifiers resolve, left to right — the collection's own not-found error (404), for example `ERR_EVENT_NOT_FOUND` for an event path segment, `ERR_TICKET_NOT_FOUND` for a ticket segment, `ERR_SESSION_NOT_FOUND` for a scan-session segment and `ERR_REPORT_NOT_FOUND` for a reconciliation-report segment, as enumerated in §2.7.
5. Body identifier fields resolve — the referenced collection's own not-found error (404), for example `ERR_ZONE_NOT_FOUND` for an unresolved `access_zone_id` and `ERR_PATRON_NOT_FOUND` for an unresolved `holder_patron_id`; applies on direct ticket issuance, gate creation, transfer creation, resale listing creation, credential-request drafting and scan-session opening.
6. Referenced zone or gate belongs to the same event — `ERR_CROSS_EVENT_REFERENCE` (422), on direct ticket issuance, gate creation and credential-request drafting.
7. Patron ownership per §2.1 — `ERR_NOT_TICKET_HOLDER` (403), on device binding, binding release, transfer creation, transfer acceptance, transfer decline, resale listing creation and delisting.
8. Stale-version guard per §2.6 — `ERR_STALE_TICKET_VERSION`, `ERR_STALE_GATE_VERSION` or `ERR_STALE_EVENT_VERSION` (412).
9. The acted-on resource is in a state from which this operation is declared — `ERR_INVALID_STATE` (409), on every action endpoint. This rule is scoped to the resource named in the path.
10. The target ticket is not `VOIDED` — `ERR_TICKET_VOIDED` (409), on device binding, transfer creation, resale listing creation, live scanning and offline batch upload.
11. The scan session's gate has `status` `SCANNING` — `ERR_GATE_NOT_SCANNING` (409), on live scanning and offline batch upload. This sits deliberately *above* rule 15 so that both session errors stay reachable: closing a session flips the gate to `IDLE` and the session to `CLOSED`, and that combination must report `ERR_GATE_NOT_SCANNING`, leaving `ERR_SESSION_NOT_OPEN` to the `SYNCING` case where the gate is still `SCANNING`.
12. An offline batch targets a session whose `mode` is `OFFLINE_CAPABLE` — `ERR_SESSION_NOT_OFFLINE_CAPABLE` (409), on offline batch upload.
13. The event's `status` permits the operation — `ERR_EVENT_STATE_FORBIDS_OPERATION` (409). Access-zone and gate creation require `DRAFT`; direct issuance and credential submission and approval require `ON_SALE` or `DOORS_OPEN`; scanning and offline upload require `DOORS_OPEN` or `IN_PROGRESS`; cutting a reconciliation report requires `CLOSED` or `RECONCILED`. `RECONCILED` passes this rule on purpose, so that the more specific rule 17 owns the already-reconciled refusal instead of being shadowed here.
14. Transfers require the logical clock strictly before the event's `transfer_window_closes_at` and an event `status` of `ON_SALE` or `DOORS_OPEN` — `ERR_EVENT_STATE_FORBIDS_TRANSFER` (409), on transfer creation and transfer acceptance.
15. The scan session is `OPEN` — `ERR_SESSION_NOT_OPEN` (409), on live scanning only. A second offline batch against a `SYNCING` or `CLOSED` session is not a declared session transition and is therefore caught earlier, at rule 9, as `ERR_INVALID_STATE`.
16. The target zone's `posture` is not `FROZEN` — `ERR_ZONE_FROZEN` (409), on credential-request submission and approval.
17. The event already carries a `FINAL` reconciliation report, or its `status` is already `RECONCILED` — `ERR_EVENT_ALREADY_RECONCILED` (409), on reconciliation-report creation.
18. Segregation of duties: the deciding `X-User-ID` differs from the request's `requested_by_user_id` — `ERR_SEGREGATION_OF_DUTIES` (403), on credential-request approval and rejection.
19. `dedupe_key` is unused within the scan session — `ERR_DUPLICATE_DEDUPE_KEY` (409), on live scanning.
20. The presented barcode's seed part resolves to a ticket of this event — `ERR_COUNTERFEIT_BARCODE` (422), on live scanning and offline batch items.
21. The presented epoch index lies inside the accepted window of §2.11 — `ERR_BARCODE_EPOCH_INVALID` (422), on live scanning and offline batch items.
22. The ticket's `device_binding_status` is `BOUND` and the presented `device_fingerprint` equals its `bound_device_fingerprint` — `ERR_DEVICE_MISMATCH` (422), on live scanning and offline batch items.
23. An entry scan is refused when the ticket's `admission_status` is already `INSIDE` — `ERR_DUPLICATE_SCAN` (409), on live scanning and offline batch items.
24. Re-entry lockout per §3.7 — `ERR_REENTRY_LOCKOUT` (409), on live scanning only.
25. Zone entitlement: the gate's `access_zone_id` equals the ticket's `access_zone_id`, and the ticket's `ticket_type` is `CREDENTIAL` whenever the zone's `required_entitlement_level` is `BACK_OF_HOUSE` — `ERR_ZONE_NOT_ENTITLED` (403), on live scanning and offline batch items.
26. Zone fire code: admitting one more person keeps the zone's `occupancy_count` at or below its `fire_code_capacity` — `ERR_ZONE_CAPACITY_FULL` (409), on live scanning only.
27. Event fire code: admitting one more person keeps the event's `live_occupancy` at or below its `fire_code_capacity` — `ERR_EVENT_FIRE_CODE_FULL` (409), on live scanning only.
28. The acting patron's `fraud_risk_score` is strictly below 40 — `ERR_PATRON_FRAUD_BLOCKED` (403), on resale listing creation and transfer creation.
29. Gate session non-overlap per §3.7 — `ERR_GATE_SESSION_OVERLAP` (409), on scan-session opening.
30. Transfer limit: the ticket's `transfer_count` is strictly below the event's `transfer_limit_per_ticket` — `ERR_TRANSFER_LIMIT_EXCEEDED` (409), on transfer creation and transfer acceptance.
31. Zone credential window capacity per §3.4 — `ERR_ZONE_CREDENTIAL_WINDOW_CAPACITY` (409), on credential-request approval.
32. Identity: a transfer recipient's `identity_verified` is true, and a resale buyer's `identity_verified` is true — `ERR_RECIPIENT_NOT_VERIFIED` (422), on transfer creation, transfer acceptance and resale purchase.
33. `COMP` and `CREDENTIAL` tickets may be neither transferred nor listed — `ERR_TICKET_NOT_TRANSFERABLE` (422), on transfer creation and resale listing creation.
34. The listing's `marketplace` is a verified channel — `ERR_MARKETPLACE_NOT_VERIFIED` (422), on resale listing creation.
35. `ask_price_cents` does not exceed the computed cap — `ERR_PRICE_CAP_EXCEEDED` (422), on resale listing creation.
36. The event's `settlement_pool_cents` covers the remediation credit — `ERR_SETTLEMENT_POOL_INSUFFICIENT` (409), on incident remediation.
37. Finalization variance tolerance — `ERR_ATTENDANCE_VARIANCE_UNRESOLVED` (409), on report finalization.
38. `zone_code` and `gate_code` are unique within the event — `ERR_DUPLICATE_CODE` (409), on access-zone and gate creation.
39. A patron's `email` is globally unique, compared case-insensitively — `ERR_DUPLICATE_EMAIL` (409), on patron registration.
40. Revision ceiling on resubmission — `ERR_MAX_REVISIONS_EXCEEDED` (409), on credential-request submission.
41. The purchasing patron is not the listing's seller — `ERR_SELF_PURCHASE` (422), on resale purchase.

## 3. Business Logic & Workflows

### 3.1. Standing Up an Event

A `VenueAdmin` opens the season by creating an **Event**, which is the root of everything else. Creation takes the event's `name` as printed on tickets, the `venue_name` it is staged at, the venue-wide `fire_code_capacity` (at least 1), the `barcode_anchor_at` instant from which barcode epochs are counted, the advertised `doors_open_at` and `event_start_at` instants, and the `transfer_window_closes_at` instant after which no handover may be created or accepted. Two policy fields are optional: `price_cap_regime`, which selects the resale ceiling rule and is one of `STATUTORY`, `VENUE_POLICY` or `NONE` and defaults to `VENUE_POLICY`; and `transfer_limit_per_ticket`, a non-negative integer capping how many accepted handovers any single ticket of this event may absorb, defaulting to 2. A fresh event lands in `DRAFT` with `live_occupancy`, `peak_live_occupancy`, `entitlements_outstanding` and `settlement_pool_cents` all at zero.

While the event is still `DRAFT` — and only then — the admin lays out its physical geography. An **AccessZone** is created with a `zone_code` unique within the event, a `required_entitlement_level` of `GA`, `PREMIUM` or `BACK_OF_HOUSE`, its own `fire_code_capacity` of at least 1, and a `face_value_reference_cents` of at least 0 used to price give-aways into that zone. Two further inputs are optional: `credential_capacity`, a non-negative ceiling on how many credential holders may be admissible at any single instant, defaulting to 0; and `comp_discount_pct`, a fraction between 0 and 1 inclusive applied against the reference face value when a complimentary or credential entitlement is issued into the zone, defaulting to 0.85. A new zone begins with `occupancy_count` and `issued_entitlement_count` at zero, `comp_forgone_cents` at zero, and a `posture` of `OPEN`. A duplicate `zone_code` within the same event is rejected with `ERR_DUPLICATE_CODE`.

A **Gate** is likewise created only while the event is `DRAFT`. It carries a `gate_code` unique within the event, an `access_zone_id` naming the zone it admits into, a rated `throughput_per_minute` of at least 1 for one open lane, and an optional `lanes_open` count of at least 1 that defaults to 1. Gates begin `IDLE` with `admitted_scan_count` at zero, a null `last_session_closed_at`, and `version` 1. A gate's `status` is `IDLE` whenever no session is open on it and `SCANNING` while one is; `last_session_closed_at` mirrors the `closed_at` of the most recently closed session on that gate and stays null until one closes; and `admitted_scan_count` is the number of scan events recorded through that gate whose `result` is `ADMITTED`.

The event then walks a fixed chain, driven by a `VenueAdmin` supplying a `target_status`. `DRAFT → ON_SALE` requires the event to have at least one access zone and at least one gate; an attempt without both is refused with `ERR_INVALID_STATE`, as is any target that is not the declared successor of the current status. Reaching `ON_SALE` is what unlocks ticket issuance and credential-request submission. `ON_SALE → DOORS_OPEN` has no further preconditions and unlocks scan-session creation. `DOORS_OPEN → IN_PROGRESS` has no preconditions either, and from `IN_PROGRESS` onward transfer creation is refused with `ERR_EVENT_STATE_FORBIDS_TRANSFER`. `IN_PROGRESS → CLOSED` requires that no scan session on any gate of the event is still `OPEN` or `SYNCING`; when it succeeds, every gate of the event is forced back to `IDLE` and reconciliation-report creation becomes permitted. The final status, `RECONCILED`, is never requested directly: the system sets it when a reconciliation report for the event is finalized, and once the event is `RECONCILED` no further report may be cut, which is reported as `ERR_EVENT_ALREADY_RECONCILED`. Each accepted advance increments the event's `version` by one.

Every consequential action is written to an append-only audit trail scoped to the event. An entry records the `event_id` it belongs to, a polymorphic pair of `subject_type` — one of `CREDENTIAL_REQUEST`, `TICKET`, `RESALE_LISTING`, `DENIED_ENTRY_INCIDENT` or `RECONCILIATION_REPORT` — and `subject_id` identifying the audited row, the `action` verb, the `actor_role` and `actor_user_id` of whoever acted, the `occurred_at` logical instant, and a human-readable `detail` summarizing amounts and the state transition. The verbs written by this system are `CREDENTIAL_REQUEST_SUBMITTED`, `CREDENTIAL_REQUEST_CHANGES_REQUESTED`, `CREDENTIAL_REQUEST_APPROVED`, `CREDENTIAL_REQUEST_REJECTED`, `TICKET_VOIDED`, `RESALE_LISTED`, `RESALE_SOLD`, `RESALE_LISTING_SUSPENDED`, `DENIED_ENTRY_REMEDIATED`, `DENIED_ENTRY_DISMISSED` and `RECONCILIATION_FINALIZED`. The trail is readable by `SecurityInvestigator` and `VenueAdmin` and may be narrowed by `subject_type`, `subject_id` and `action`.

### 3.2. Patron Accounts, Identity and Device Binding

A `BoxOfficeAgent` registers a **Patron** with an `email` and a `display_name`. The email is globally unique compared case-insensitively, so a second registration differing only in letter case is rejected with `ERR_DUPLICATE_EMAIL`. A new patron starts with `identity_verified` false, `device_rebind_count`, `strike_count`, `fraud_risk_score`, `remediation_credit_cents` and `payout_balance_cents` all at zero, and a `fraud_risk_basis` of `PROVISIONAL`. Later, once the agent has physically inspected a government ID, recording the check with a `document_reference` flips `identity_verified` to true and increments the patron's `version`. Verification is not cosmetic: an unverified patron may not receive a transferred entitlement, may not buy on the resale market, may not list one of their own tickets, and under the statutory resale regime is denied any markup at all.

Device binding is the second half of the anti-screenshot defence. A `Patron` binds a `device_fingerprint` to a ticket they hold, which sets that ticket's `bound_device_fingerprint` and moves its `device_binding_status` from `UNBOUND` to `BOUND`. Because a rotating barcode is only as good as the device that renders it, a scan is refused unless the fingerprint presented at the turnstile equals the one bound to the ticket. A holder who changes phones releases the binding, which clears `bound_device_fingerprint` to null and sets `device_binding_status` to `RELEASED`; a released ticket is as unscannable as an unbound one until a new device is bound. Binding and releasing each increment the ticket's `version`.

Rebinding is tracked because serial rebinding is a fraud signal. Whenever a device is bound to a ticket whose `device_binding_status` was already `BOUND` or `RELEASED` — that is, on any binding after the first on that ticket — the holder's `device_rebind_count` increases by one and their `fraud_risk_score` is immediately recomputed under the provisional reading described in §2.10. A patron who churns devices across their collection can therefore price themselves out of the resale market without ever being denied at a gate.

### 3.3. Issuing Entitlements at the Box Office

Once the event is `ON_SALE` or `DOORS_OPEN`, a `BoxOfficeAgent` issues a **Ticket** directly — a paid sale or a manual will-call hold — by naming the `event_id`, the `access_zone_id` the ticket entitles its holder to, the `holder_patron_id` who will hold it, a `ticket_type` of `PAID`, `COMP`, `WILL_CALL` or `CREDENTIAL`, and a `face_value_cents` of at least 0. Complimentary and credential entitlements carry a `face_value_cents` of 0. Issuance mints the ticket's `barcode_seed`, the server-side secret every rotating barcode for that ticket is derived from, and opens the ticket in `lifecycle_status` `ISSUED`, `admission_status` `NOT_ADMITTED` and `device_binding_status` `UNBOUND`, with `transfer_count`, `admitted_scan_count` at zero and `bound_device_fingerprint`, `last_admitted_at`, `last_exited_at` and `credential_request_id` all null.

Issuance moves three counters. The target zone's `issued_entitlement_count` rises by one and its `posture` is recomputed; the event's `entitlements_outstanding` rises by one; and only when the `ticket_type` is `PAID` does the event's `settlement_pool_cents` rise by the ticket's `face_value_cents`. A will-call hold contributes nothing to the pool because nothing was collected through this channel.

A ticket carries **two independent status dimensions**, and confusing them is the single most common modelling error here. `lifecycle_status` is the commercial dimension — `ISSUED`, `LISTED`, `TRANSFERRED`, `RESOLD` or `VOIDED` — and `admission_status` is the physical-presence dimension — `NOT_ADMITTED`, `INSIDE`, `EXITED` or `DENIED_FLAGGED`. Neither constrains the other's value directly: a ticket whose holder is already `INSIDE` keeps `admission_status` `INSIDE` even after the entitlement is voided, and a ticket that is `INSIDE` may still be listed and delisted on the commercial dimension. `VOIDED` is terminal on the commercial dimension; the presence dimension has no terminal value at all. Two derived timestamps track presence: `last_admitted_at` holds the `recorded_at` of the most recent admitted scan on the ticket and stays null until the first one, and `last_exited_at` holds the `recorded_at` of the most recent exit scan and stays null until the first exit. `admitted_scan_count` counts admitted scans on the ticket across every source.

A zone's **posture** governs whether give-aways may still be poured into it, and it is recomputed every time the zone's `issued_entitlement_count` changes — on direct issuance, on the credential-approval cascade, and on a void. The posture is derived from the exact ratio of `issued_entitlement_count` to the zone's `fire_code_capacity`, compared without rounding: the posture is `FROZEN` when that ratio is at least 1.00, `RESTRICTED` when it is at least 0.90 but below 1.00, and `OPEN` otherwise. Both boundaries are inclusive. `RESTRICTED` is advisory and still permits credential submission and approval; `FROZEN` blocks both, with `ERR_ZONE_FROZEN`. Voided tickets are excluded from the count, so a void can thaw a frozen zone.

### 3.4. Complimentary, Will-Call and Credential Distribution

Non-sale distribution runs through an approval workflow with segregation of duties, because give-aways are where revenue quietly leaks. A `BoxOfficeAgent` drafts a **CredentialRequest** naming the `event_id`, the `access_zone_id` the issued entitlements will admit into, the `recipient_patron_id` who will hold every one of them, a `distribution_type` of `COMP`, `WILL_CALL` or `CREDENTIAL`, a `quantity` between 1 and 50 inclusive, a `valid_from` instant that opens the validity window inclusively, a `valid_until` instant that closes it exclusively and must be strictly after `valid_from`, and a free-text `justification` recorded in the audit trail. A draft opens in `DRAFT` with `revision_count` and `issued_ticket_count` at zero, `forgone_revenue_cents` at zero, and `requested_by_user_id` and `approved_by_user_id` both null.

Submission moves the request to `SUBMITTED` and stamps `requested_by_user_id` with the submitting agent's `X-User-ID`. Submission requires the event to be `ON_SALE` or `DOORS_OPEN` and the target zone's `posture` to be anything other than `FROZEN`, and it appends an audit entry with the action `CREDENTIAL_REQUEST_SUBMITTED`.

From `SUBMITTED`, a `TicketingApprover` has three moves, and the two terminal ones are guarded identically. Returning the request for revision moves it to `CHANGES_REQUESTED` with an approver `note` and appends `CREDENTIAL_REQUEST_CHANGES_REQUESTED`. **Rejecting** it requires the request to be `SUBMITTED` and the approver's `X-User-ID` to differ from `requested_by_user_id`; it takes a `note`, moves the request to `REJECTED`, stamps `approved_by_user_id` with the approver's identifier, issues no ticket whatsoever, and appends `CREDENTIAL_REQUEST_REJECTED`. **Approving** it requires the same two conditions plus a zone `posture` other than `FROZEN` and, for credential distributions, window capacity; it takes an optional `note`, moves the request to `APPROVED`, stamps `approved_by_user_id`, and appends `CREDENTIAL_REQUEST_APPROVED`. An approver who tries to decide their own submission is refused with `ERR_SEGREGATION_OF_DUTIES`, whichever of the two decisions they attempt.

A request returned as `CHANGES_REQUESTED` re-enters `SUBMITTED` on resubmission, and resubmission carries its own ceiling. It again requires the event to be `ON_SALE` or `DOORS_OPEN` and the zone not to be `FROZEN`, and additionally requires `revision_count` to be strictly below 2; a third resubmission is refused with `ERR_MAX_REVISIONS_EXCEEDED`. A successful resubmission increments `revision_count` by one and overwrites `requested_by_user_id` with the resubmitting agent's `X-User-ID` — which means the segregation-of-duties comparison at approval time is against whoever last touched the request, not whoever originally drafted it. `revision_count` moves only on a resubmission out of `CHANGES_REQUESTED`; the first submission out of `DRAFT` leaves it at zero.

Credential passes are limited **per zone per instant** rather than per event, because two non-overlapping shifts may legitimately each fill the back of house. Two validity windows overlap when the first starts strictly before the second ends and the second starts strictly before the first ends; windows that merely touch — one ending at exactly the instant the other begins — do not overlap, so the later shift starts from a clean slate. Approving a `CREDENTIAL` distribution therefore sums the `quantity` of every already-`APPROVED` credential request in the same zone whose window overlaps the candidate's window, adds the candidate's own `quantity`, and requires the total to be no greater than the zone's `credential_capacity`. Equality is accepted; one pass beyond is refused with `ERR_ZONE_CREDENTIAL_WINDOW_CAPACITY`. Complimentary and will-call distributions are not subject to this ceiling.

Approval is where the cascade fires, and it fires in a fixed order. First, the forgone revenue is booked. The per-ticket forgone amount is the zone's `face_value_reference_cents` multiplied by one minus the zone's `comp_discount_pct`, rounded half up to a whole cent; the request's `forgone_revenue_cents` is that per-ticket figure multiplied by the request's `quantity`. Rounding is per ticket and only then multiplied — computing the whole-batch product first and rounding once is wrong. Second, as many tickets as the `quantity` are auto-issued to the `recipient_patron_id` in the request's zone, each with `ticket_type` equal to the request's `distribution_type`, `face_value_cents` of 0, `credential_request_id` pointing back at this request, `lifecycle_status` `ISSUED`, `admission_status` `NOT_ADMITTED` and `device_binding_status` `UNBOUND`, each with its own freshly minted `barcode_seed`; because the face value is zero, the event's `settlement_pool_cents` does not move. Third, per issued ticket the zone's `issued_entitlement_count` and the event's `entitlements_outstanding` each rise by one, and the zone's `comp_forgone_cents` accumulates the booked forgone revenue. Fourth, the zone's `posture` is recomputed from its new `issued_entitlement_count`. Finally `issued_ticket_count` is set to the approved `quantity`.

### 3.5. Handing Over an Entitlement

A `Patron` who holds a ticket may offer it to someone else by creating a **TransferRequest** naming the `ticket_id` and the intended `to_patron_id`; the server records the acting patron as `from_patron_id`. The offer opens in `PENDING` with a null `decided_at`. Creating an offer requires the acting patron to be the ticket's holder, the ticket not to be `VOIDED`, the acting patron's `fraud_risk_score` to be strictly below 40, the logical clock to be strictly before the event's `transfer_window_closes_at`, the event's `status` to be `ON_SALE` or `DOORS_OPEN`, the ticket's `transfer_count` to be strictly below the event's `transfer_limit_per_ticket`, the intended recipient's `identity_verified` to be true, and the ticket's `ticket_type` not to be `COMP` or `CREDENTIAL` — complimentary and credential entitlements are non-transferable and are refused with `ERR_TICKET_NOT_TRANSFERABLE`. Several offers may sit `PENDING` on the same ticket at once; the first decision resolves all of them.

**Acceptance** is the recipient's move and is the transition that actually moves the entitlement. It requires the offer to be `PENDING`, the acting patron to be the named `to_patron_id`, the logical clock to be strictly before `transfer_window_closes_at`, the ticket's `transfer_count` to be strictly below the event's `transfer_limit_per_ticket`, the recipient's `identity_verified` to be true, and the ticket's `lifecycle_status` to be `ISSUED` or `TRANSFERRED`. On success the offer moves `PENDING → ACCEPTED` with `decided_at` set to the logical clock; the ticket's `holder_patron_id` becomes the recipient; the ticket's `lifecycle_status` becomes `TRANSFERRED` (a second and further handover simply stays at `TRANSFERRED`, with `transfer_count` continuing to accumulate toward the event's limit); `transfer_count` rises by one; the device binding is released, so `device_binding_status` becomes `RELEASED` and `bound_device_fingerprint` becomes null, forcing the new holder to bind their own phone before they can be scanned in; every *other* `PENDING` offer on the same ticket is set to `DECLINED` with its own `decided_at` stamped; and the ticket's `version` increments. The event's `entitlements_outstanding` does not move, because the entitlement changed hands rather than coming into or going out of existence.

**Declining** is the mirror move and may be performed by either party — the acting patron must be the offer's `to_patron_id` or its `from_patron_id`, and anyone else is refused with `ERR_NOT_TICKET_HOLDER`. It requires the offer to be `PENDING`, moves it `PENDING → DECLINED`, stamps `decided_at` with the logical clock, and leaves the ticket entirely untouched: `holder_patron_id` is unchanged, `lifecycle_status` is unchanged, `transfer_count` does not move, the device binding is not released and the ticket's `version` does not increment. A decline is deliberately cheaper to authorize than an acceptance: because nothing moves, the transfer window, the per-ticket transfer limit and the recipient's `identity_verified` flag are all irrelevant to it and are not evaluated, so an offer left stranded after the window closed can still be tidied away. A decline also resolves only the offer it names — every other `PENDING` offer on the same ticket stays `PENDING` and remains decidable, which is the opposite of what an acceptance does. Both `ACCEPTED` and `DECLINED` are terminal, so re-deciding an already-decided offer is refused with `ERR_INVALID_STATE`.

### 3.6. Verified Resale, Price Caps and Settlement

A holder who wants out lists the entitlement instead of gifting it. Creating a **ResaleListing** takes the `ticket_id`, the `ask_price_cents` of at least 0, the `marketplace` channel — one of `VERIFIED_PRIMARY`, `VERIFIED_PARTNER` or `UNVERIFIED` — and the `expected_ticket_version` guard of §2.6. The server records the acting patron as `seller_patron_id`, leaves `buyer_patron_id` null, and sets `superseded_listing_id` to the most recent `DELISTED` or `SUSPENDED` listing on the same ticket ordered by `created_at` descending, or null when this is the ticket's first listing. Listing moves the ticket `ISSUED → LISTED` (or `TRANSFERRED → LISTED` for a ticket that has changed hands), opens the listing in `LISTED` with `platform_fee_cents`, `venue_royalty_cents`, `processing_fee_cents` and `seller_payout_cents` all null, increments the ticket's `version`, and appends an audit entry with the action `RESALE_LISTED` against `subject_type` `RESALE_LISTING`.

Listing is gated tightly. The acting patron must be the ticket's `holder_patron_id`, the ticket must not be `VOIDED`, the seller's `fraud_risk_score` must be strictly below 40, the seller's `identity_verified` must be true, the ticket's `ticket_type` must be `PAID` (a `COMP`, `WILL_CALL` or `CREDENTIAL` ticket is refused, and the give-away types are refused with `ERR_TICKET_NOT_TRANSFERABLE`), the ticket's `admission_status` must still be `NOT_ADMITTED` — someone already inside the venue cannot sell their way out — and the event's `status` must be `ON_SALE` or `DOORS_OPEN`.

Offering an entitlement through an **unverified** channel is itself the unauthorized-resale signal, and it is the one adjudication failure outside the turnstile that still leaves evidence behind. A `marketplace` of `UNVERIFIED` is refused with `ERR_MARKETPLACE_NOT_VERIFIED`, no listing row is created and the ticket's `lifecycle_status` is unchanged — but a denied-entry incident *is* opened with `category` `UNAUTHORIZED_RESALE`, its `ticket_id` set to the offered ticket and its `patron_id` set to the acting seller, a strike is booked against that seller's `strike_count`, and the seller's `fraud_risk_score` is recomputed under the provisional reading. Two such attempts push a previously clean seller from 0 to 60 and out of the market entirely.

The **price cap** for a listing is computed before the asking price is compared against it, and it is written to the listing as `cap_price_cents`. The cap is derived in branches. When the ticket's `ticket_type` is `COMP` or `CREDENTIAL`, the cap is 0, because non-transferable give-aways may never be resold at any price. When the event's `price_cap_regime` is `NONE`, there is no cap at all and any `ask_price_cents` of at least 0 is accepted. Otherwise a percentage is selected from the regime — 0.10, that is ten percent, under `STATUTORY`, and 0.30, that is thirty percent, under `VENUE_POLICY` — and the permitted markup is the ticket's `face_value_cents` multiplied by that percentage, rounded half up to a whole cent, then reduced to 2500 cents if it came out higher; the cap is the ticket's `face_value_cents` plus that markup. One override then applies: under the `STATUTORY` regime, if the acting seller's `identity_verified` is false, the cap collapses to exactly the ticket's `face_value_cents`, because the statute forbids an unverified seller any markup whatsoever. A listing is accepted when there is no cap or when `ask_price_cents` is less than or equal to the cap; equality is accepted, and only a strictly greater ask is refused with `ERR_PRICE_CAP_EXCEEDED`.

A seller may **withdraw** a live listing. Delisting requires the listing to be `LISTED` and the acting patron to be its `seller_patron_id`, and anyone else is refused with `ERR_NOT_TICKET_HOLDER`; it moves the listing `LISTED → DELISTED`, reverts the ticket's `lifecycle_status` to `ISSUED`, and increments the ticket's `version`. Because no sale occurred, no money changes hands: `platform_fee_cents`, `venue_royalty_cents`, `processing_fee_cents` and `seller_payout_cents` all stay null, `buyer_patron_id` stays null, the seller's `payout_balance_cents` does not move, the event's `settlement_pool_cents` does not move, and the event's `entitlements_outstanding` is unchanged because the entitlement never left existence. The withdrawn row is retained rather than deleted, keeping its computed `cap_price_cents` and its own `superseded_listing_id`, and a later listing on the same ticket will point its `superseded_listing_id` at this one. `DELISTED` is terminal, so a second withdrawal of the same listing is refused with `ERR_INVALID_STATE`.

A **purchase** is a different patron's move. It requires the listing to be `LISTED`, its `marketplace` to be `VERIFIED_PRIMARY` or `VERIFIED_PARTNER`, the acting patron to be someone other than the `seller_patron_id` (a seller buying their own listing is refused with `ERR_SELF_PURCHASE`), the buyer's `identity_verified` to be true, and the event's `status` to be `ON_SALE` or `DOORS_OPEN`. On success the listing moves `LISTED → SOLD` with `buyer_patron_id` set to the buyer, the ticket moves `LISTED → RESOLD`, the ticket's `holder_patron_id` becomes the buyer, and the ticket's `device_binding_status` becomes `RELEASED` with `bound_device_fingerprint` cleared to null — the new holder must bind their own device. An audit entry with the action `RESALE_SOLD` is appended.

Settlement is split at purchase from the listing's `ask_price_cents` as it stands at that moment, and **each component is rounded independently before anything is added**. `platform_fee_cents` is the sale price multiplied by 0.0725, that is 7.25 percent, rounded half up. `venue_royalty_cents` is the sale price multiplied by 0.0350, that is 3.50 percent, rounded half up. `processing_fee_cents` is the sale price multiplied by 0.0290, that is 2.90 percent, rounded half up, plus a flat 30 cents. `seller_payout_cents` is the sale price minus the sum of those three rounded components. Rounding one combined percentage and adding the flat fee afterwards produces a different — and incorrect — payout. The seller's `payout_balance_cents` then rises by `seller_payout_cents` and the event's `settlement_pool_cents` rises by `venue_royalty_cents`; the platform and processing components leave the system. No patron or event attribute other than the ask price enters the split.

A listing can also be taken off the market against the seller's will, and this is a system-driven transition rather than an operator action. When a denied-entry incident is created against a patron and their recomputed `fraud_risk_score` reaches 40, or when a ticket carrying a live listing is voided, every `LISTED` listing of that seller moves `LISTED → SUSPENDED` and an audit entry with the action `RESALE_LISTING_SUSPENDED` is appended. Suspension reverts the affected ticket's `lifecycle_status` from `LISTED` back to `ISSUED`, except where the ticket is itself being voided, in which case the void's own terminal status wins.

### 3.7. Gate Operations: Sessions, Scanning and the Offline Cache

Scanning is organized into sessions. A `GateOperator` opens a **ScanSession** by naming the `gate_id`, the handheld's `operator_device_id`, a `mode` of `ONLINE` or `OFFLINE_CAPABLE`, and the `expected_gate_version` guard. Opening requires the event's `status` to be `DOORS_OPEN` or `IN_PROGRESS` and requires that the logical clock not fall inside the half-open interval from any existing session's `opened_at` up to but not including its `closed_at`, where a still-`OPEN` or `SYNCING` session is treated as having no upper bound. A new session opening at exactly a prior session's `closed_at` is accepted, because that boundary is excluded. This interval rule is the *only* thing governing gate occupancy at session creation: an attempt to open a second session on a gate that is already `SCANNING` must report `ERR_GATE_SESSION_OVERLAP` and never `ERR_INVALID_STATE`. A successful open creates the session in `OPEN` with `opened_at` set to the logical clock, a null `closed_at`, and `online_scan_count`, `offline_uploaded_count` and `duplicate_suppressed_count` all at zero; the gate moves `IDLE → SCANNING` and its `version` increments.

Closing the session is permitted from `OPEN` or from `SYNCING`. It sets the session's `status` to `CLOSED` and its `closed_at` to the logical clock, moves the gate `SCANNING → IDLE`, copies that `closed_at` onto the gate's `last_session_closed_at`, and increments the gate's `version`. Closing a session that is already `CLOSED` is not a declared transition and is refused with `ERR_INVALID_STATE`.

A live scan is submitted with the `presented_barcode`, the `device_fingerprint` of the device that rendered it, a `direction` of `IN` or `OUT`, a `dedupe_key` that must be unused within the session, and an optional `scanned_at` client instant that defaults to the logical clock. The server persists a **ScanEvent** with its `scan_session_id`, the `ticket_id` the seed part resolved to (null when it resolved to nothing), a `source` of `ONLINE`, a `recorded_at` equal to the logical clock, an adjudicated `result`, and a `denied_reason_code` carrying the error identifier the denial mapped to, which is null for admitted and exit results.

Adjudication is banded, and the band a failure falls into determines whether anything is written at all. Failures at rules 1 through 19 of §2.12 are **hard request errors**: nothing is persisted — no scan event, no incident, no counter movement, no strike. Failures at rules 20 through 27 are **adjudication failures on a well-formed scan**: the server persists a scan event carrying the mapped denial result and the mapped error identifier as its `denied_reason_code`, and *then* returns that error with its declared HTTP status. The eleven possible `result` values are `ADMITTED`, `EXIT_RECORDED`, `DENIED_DUPLICATE`, `DENIED_COUNTERFEIT`, `DENIED_DEVICE_MISMATCH`, `DENIED_ZONE`, `DENIED_CAPACITY`, `DENIED_VOIDED`, `DENIED_STALE_BARCODE` and `DENIED_REENTRY_LOCKOUT`.

Only five denials are **fraud-bearing**, and only those open an investigation and book a strike. `DENIED_COUNTERFEIT` maps to incident `category` `COUNTERFEIT`; `DENIED_STALE_BARCODE` also maps to `COUNTERFEIT`, because an out-of-window epoch is a replayed screenshot; `DENIED_DEVICE_MISMATCH` maps to `DEVICE_MISMATCH`; `DENIED_DUPLICATE` maps to `DUPLICATE`; and `DENIED_ZONE` maps to `ZONE_VIOLATION`. The three **operational** denials — `DENIED_CAPACITY`, `DENIED_REENTRY_LOCKOUT` and `DENIED_VOIDED` — persist their scan event but open no incident, book no strike and leave the patron's `fraud_risk_score` untouched, because a full house is not the patron's fault. Incidents with `category` `UNAUTHORIZED_RESALE` are never scan-derived; they arise only from the unverified-marketplace path of §3.6.

When a fraud-bearing denial does open an incident, the cascade runs in four links within the same request: the incident is created in `OPEN`; the holder's `strike_count` rises by one and their `fraud_risk_score` is recomputed under the provisional reading; if that recomputed score reaches 40, every `LISTED` listing of that patron is suspended; and each suspended listing reverts its ticket's `lifecycle_status` to `ISSUED`. One special case breaks the chain: when the seed part resolves to no ticket at all, there is no holder to punish, so the persisted scan event and the `COUNTERFEIT` incident both carry a null `ticket_id`, the incident carries a null `patron_id`, no strike is booked and no risk score moves — the incident still opens so the denial remains auditable.

An **entry** scan that survives the whole ladder is `ADMITTED`. Admission requires the session to be `OPEN` and its gate to be `SCANNING`, the event to be `DOORS_OPEN` or `IN_PROGRESS`, the presented barcode to fall inside the acceptance window of §2.11, the presented `device_fingerprint` to equal the ticket's `bound_device_fingerprint`, the gate's `access_zone_id` to equal the ticket's `access_zone_id`, the ticket not to be `VOIDED`, and both fire-code ceilings to still have room for one more person. Admission moves the ticket `NOT_ADMITTED → INSIDE`, refreshes `last_admitted_at` and increments the ticket's `admitted_scan_count`, raises the zone's `occupancy_count` and the event's `live_occupancy` by one each, raises the event's `peak_live_occupancy` whenever the new live figure exceeds it, and increments the gate's `admitted_scan_count` and the session's `online_scan_count`.

An **exit** scan is far simpler: it requires the ticket's `admission_status` to be `INSIDE` and the session to be `OPEN`, persists a scan event with `result` `EXIT_RECORDED`, moves the ticket `INSIDE → EXITED`, sets `last_exited_at` to the logical clock, and lowers the zone's `occupancy_count` and the event's `live_occupancy` by one each, conserving the head count.

Re-entry is allowed but rate-limited per ticket. The lockout is a **closed** interval anchored on the ticket's own `last_exited_at` and running 120 seconds — two minutes — beyond it, with both ends inclusive; an entry scan is permitted only when the logical clock is strictly later than `last_exited_at` plus 120 seconds. An attempt at exactly the upper bound is rejected with `ERR_REENTRY_LOCKOUT`, and the first accepted instant is one second later. The window is per ticket, not per patron: a second ticket held by the same person carries its own independent window, which is what stops a phone being handed back over the fence on one barcode while permitting a legitimate second holder to walk in. A re-entry that clears the lockout moves the ticket `EXITED → INSIDE` and produces exactly the same counter movements as a first admission.

Two denials move the presence dimension. A duplicate entry scan on a ticket that is already `INSIDE` moves it `INSIDE → DENIED_FLAGGED`, persists a scan event with `result` `DENIED_DUPLICATE` and `denied_reason_code` of `ERR_DUPLICATE_SCAN`, opens a `DUPLICATE` incident, and leaves the occupancy counters alone. A device mismatch, a zone violation or an out-of-window barcode on a ticket that has not yet entered moves it `NOT_ADMITTED → DENIED_FLAGGED`, persists the scan event with the mapped denial result and reason code, opens an incident of the mapped category, and likewise leaves the occupancy counters alone. Denials with no declared transition — capacity refusals, the re-entry lockout and the voided-ticket case — leave the ticket's `admission_status` exactly as it was.

The **offline cache** is the fallback for a gate that loses its uplink. Uploading requires the session's `mode` to be `OFFLINE_CAPABLE`, and the payload is a single `scans` field holding a non-empty array of objects each carrying exactly a `presented_barcode`, a `device_fingerprint`, a `direction`, a `dedupe_key` and a `scanned_at`. Unlike a live scan, `scanned_at` is mandatory on every item, and it is the instant against which that item's barcode epoch is evaluated — which is precisely why a cache recorded before the uplink came back is still accepted. Items are adjudicated in ascending `scanned_at` order, tie-broken by their position in the array, and the upload is best-effort per item: a failing item is recorded rather than aborting the batch. Each item is persisted as a scan event with `source` `OFFLINE_BATCH`, a `recorded_at` of the logical clock and a `scanned_at` of the item's own client instant. Taking an upload moves the session `OPEN → SYNCING`, after which it accepts no further live scan and reports `ERR_SESSION_NOT_OPEN`; a second upload against a `SYNCING` or `CLOSED` session is not a declared transition and is refused with `ERR_INVALID_STATE`.

Offline adjudication differs from live adjudication in three respects. Admitted items set the ticket's `admission_status` to `INSIDE` and refresh its `last_admitted_at`, but they leave the event's `live_occupancy` and the zone's `occupancy_count` untouched, because the live reading excludes offline-sourced scans — they surface only in the reconciled reading. Neither fire-code ceiling nor the re-entry lockout is evaluated for a batch item, so `DENIED_CAPACITY` and `DENIED_REENTRY_LOCKOUT` cannot arise from an upload. And a batch item presenting a `VOIDED` ticket is recorded as `DENIED_VOIDED` with a `denied_reason_code` of `ERR_TICKET_VOIDED` rather than aborting the upload — a live scan of a voided ticket is instead stopped early at rule 10 of §2.12 and therefore persists nothing at all, which makes `DENIED_VOIDED` a result only the offline path can produce. Denied items otherwise open incidents exactly as online denials do.

The upload answers with pinned counter semantics. `accepted_count` counts items adjudicated `ADMITTED` or `EXIT_RECORDED`. `duplicate_suppressed_count` counts items adjudicated `DENIED_DUPLICATE`. `denied_count` counts *every* non-admitted item, duplicates included, so `accepted_count` plus `denied_count` always equals the number of items submitted. `scan_event_ids` holds one identifier per item in adjudication order. On the session itself, `offline_uploaded_count` counts every item persisted whatever its result, `online_scan_count` counts the session's scan events whose `source` is `ONLINE`, and the session's own `duplicate_suppressed_count` counts every scan event in the session whose `result` is `DENIED_DUPLICATE`.

### 3.8. Denied-Entry Investigation, Remediation and Voiding

Every fraud-bearing denial leaves a **DeniedEntryIncident** for a `SecurityInvestigator` to work. An incident records the `scan_event_id` of the denial that opened it, the `ticket_id` involved (null when the barcode resolved to nothing), the `patron_id` of the holder at denial time (null when unknown), the fraud `category` derived from the denial, and a `status` that begins at `OPEN` with a null `reviewer_user_id`, a null `resolution_note` and a null `remediation_credit_cents`.

Taking an incident requires it to be `OPEN`; it moves the incident `OPEN → UNDER_REVIEW` and stamps `reviewer_user_id` with the investigator's `X-User-ID`. From `UNDER_REVIEW` the investigator has two symmetric exits, both taking a `resolution_note`.

**Remediation** requires the incident to be `UNDER_REVIEW`, its `ticket_id` to be non-null, and the event's `settlement_pool_cents` to be at least the credit about to be granted — an underfunded pool is refused with `ERR_SETTLEMENT_POOL_INSUFFICIENT`. On success the incident moves `UNDER_REVIEW → REMEDIATED`, `remediation_credit_cents` is written with the computed credit, the holder's `remediation_credit_cents` rises by that amount and the event's `settlement_pool_cents` falls by exactly the same amount, the patron's `fraud_risk_score` is recomputed under the adjudicated reading and `fraud_risk_basis` is set to `ADJUDICATED`, and an audit entry with the action `DENIED_ENTRY_REMEDIATED` is appended.

**Dismissal** requires the incident to be `UNDER_REVIEW`. It moves the incident `UNDER_REVIEW → DISMISSED`, grants no credit at all so `remediation_credit_cents` stays null, *withdraws* the strike booked when the incident was created by lowering the holder's `strike_count` by one, recomputes the patron's `fraud_risk_score` under the adjudicated reading — which drops dismissed incidents from the sum entirely — sets `fraud_risk_basis` to `ADJUDICATED`, and appends an audit entry with the action `DENIED_ENTRY_DISMISSED`.

The goodwill credit is computed in a **pinned five-step order**, and the tier looks deceptively like it should key on what the patron finally receives, which would be circular. Step one: the base credit is the ticket's `face_value_cents` when its `ticket_type` is `PAID`, and 0 for any other type. Step two: the goodwill percentage is selected **from the base credit alone** — 0.10, that is ten percent, when the base is at most 5000 cents; 0.15, that is fifteen percent, when the base is at most 15000 cents; and 0.20, that is twenty percent, otherwise, with both boundaries inclusive. Step three: the goodwill component is the base credit multiplied by that percentage, rounded half up to a whole cent. Step four: the strike penalty is 500 cents for each strike on the patron's `strike_count`, reduced to 2000 cents if that product came out higher — and `strike_count` is read *after* the strike this very incident booked at creation, so the incident under remediation counts against its own credit. Step five: the granted credit is the base plus the goodwill less the penalty, floored at 0 so it can never be negative. A complimentary ticket therefore yields a zero credit no matter how many strikes are involved.

Voiding is the investigator's blunt instrument. Voiding a ticket takes a `reason` and a `refund_to_holder` flag, requires the ticket's `lifecycle_status` not to be `VOIDED` already, and drives the ticket to `VOIDED` from `ISSUED`, from `LISTED` or from `RESOLD` while leaving `admission_status` entirely untouched — someone already inside stays counted as inside. In every case the zone's `issued_entitlement_count` falls by one and its `posture` is recomputed, and the event's `entitlements_outstanding` falls by one. When `refund_to_holder` is true *and* the ticket's `ticket_type` is `PAID`, the event's `settlement_pool_cents` falls by the ticket's `face_value_cents` and the holder's `remediation_credit_cents` rises by the same amount; when the flag is false, or the ticket was never paid for, no money moves. Voiding from `LISTED` additionally sets that ticket's `LISTED` resale listing to `SUSPENDED`. Every void appends an audit entry with `subject_type` `TICKET` and the action `TICKET_VOIDED`.

### 3.9. Post-Event Reconciliation

Once an event is `CLOSED`, a `VenueAdmin` cuts a **ReconciliationReport** against what venue operations counted at the doors. Creation takes the `reported_attendance` (at least 0) and the `expected_event_version` guard, opens the report in `DRAFT` with a null `override_reason` and a null `finalized_by_user_id`, and increments the event's `version`. At creation the report's derived figures are computed: `scan_derived_attendance` from the reconciled reading of §2.9, `variance_count` as the `reported_attendance` minus `scan_derived_attendance`, `variance_pct` as that variance divided by `scan_derived_attendance`, multiplied by 100 and rounded half up to two decimal places — defined as exactly 0.00 when `scan_derived_attendance` is zero, rather than an error — and `fire_code_breach` set true when `scan_derived_attendance` exceeds the event's `fire_code_capacity`. A negative `variance_count` and a negative `variance_pct` are entirely normal: they mean the scanners saw more people than operations reported.

**Finalization** requires the report to be `DRAFT` or `REOPENED`, and requires the absolute value of `variance_pct` to be no greater than 2.00 percent — or, failing that, a non-empty `override_reason` supplied with the request. An out-of-tolerance variance with no override is refused with `ERR_ATTENDANCE_VARIANCE_UNRESOLVED`. Finalization recomputes `scan_derived_attendance`, `variance_count`, `variance_pct` and `fire_code_breach` afresh rather than trusting the figures cut at creation, sets `status` to `FINAL`, stamps `finalized_by_user_id` with the admin's `X-User-ID`, drives the event's `status` to `RECONCILED`, and appends an audit entry with the action `RECONCILIATION_FINALIZED`.

**Reopening** is the exact inverse and requires the report to be `FINAL`. It moves the report `FINAL → REOPENED`, takes a `reason` for the correction, clears `finalized_by_user_id` back to null, and returns the event's `status` to `CLOSED` so that the reconciliation can be re-cut. A `REOPENED` report finalizes again under precisely the same tolerance rule and produces precisely the same side effects as a first finalization, including driving the event back to `RECONCILED`.

## 4. Endpoint Definitions

Operations that bring a genuinely new resource into existence — an event, an access zone, a gate, a patron, a ticket, a transfer offer, a resale listing, a credential-request draft, a scan session, a live scan event or a reconciliation report — answer with `201 Created`. Every other successful operation, including all state-advancing actions, all computed reads, all list reads and the offline batch upload, answers with `200 OK`. Where a role column lists `Any`, all six roles of §2.1 are authorized.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | VenueAdmin |
| POST | `/events` | Create an Event in DRAFT | VenueAdmin |
| GET | `/events/{id}` | Read one Event with its computed occupancy and settlement figures | Any |
| GET | `/events` | List Events | Any |
| POST | `/events/{id}/advance-status` | Advance the Event along its status chain | VenueAdmin |
| GET | `/events/{id}/occupancy` | Computed read: live occupancy, reconciled attendance and clearance projection | GateOperator, SecurityInvestigator, VenueAdmin |
| GET | `/events/{id}/audit-log-entries` | Read the event's append-only audit trail, newest first | SecurityInvestigator, VenueAdmin |
| POST | `/events/{id}/access-zones` | Create an AccessZone under the event | VenueAdmin |
| GET | `/access-zones/{id}` | Read one AccessZone including posture and occupancy | Any |
| GET | `/access-zones` | List AccessZones | Any |
| POST | `/events/{id}/gates` | Create a Gate serving one AccessZone | VenueAdmin |
| GET | `/gates/{id}` | Read one Gate including status and version | GateOperator, SecurityInvestigator, VenueAdmin |
| GET | `/gates` | List Gates | GateOperator, SecurityInvestigator, VenueAdmin |
| POST | `/patrons` | Register a Patron account | BoxOfficeAgent |
| GET | `/patrons/{id}` | Read one Patron including risk score and credit balances | Any |
| GET | `/patrons` | List Patrons | BoxOfficeAgent, SecurityInvestigator, VenueAdmin |
| POST | `/patrons/{id}/verify-identity` | Record a government-ID check | BoxOfficeAgent |
| POST | `/tickets` | Issue a ticket directly, minting its barcode seed | BoxOfficeAgent |
| GET | `/tickets/{id}` | Read one Ticket including both status dimensions and version | Any |
| GET | `/tickets` | List Tickets | Any |
| GET | `/tickets/{id}/barcode` | Computed read: the rotating barcode valid at the logical clock | Patron, BoxOfficeAgent, GateOperator, VenueAdmin |
| POST | `/tickets/{id}/device-binding` | Bind the holder's device to the ticket | Patron |
| POST | `/tickets/{id}/device-binding/release` | Release the current device binding | Patron |
| POST | `/tickets/{id}/void` | Void an entitlement, optionally refunding the holder | SecurityInvestigator |
| POST | `/transfer-requests` | Offer an entitlement to another patron | Patron |
| GET | `/transfer-requests/{id}` | Read one TransferRequest | Patron, BoxOfficeAgent, SecurityInvestigator, VenueAdmin |
| GET | `/transfer-requests` | List TransferRequests | Patron, BoxOfficeAgent, SecurityInvestigator, VenueAdmin |
| POST | `/transfer-requests/{id}/accept` | Recipient accepts the handover | Patron |
| POST | `/transfer-requests/{id}/decline` | Recipient or sender declines the handover | Patron |
| POST | `/resale-listings` | List an entitlement on a resale marketplace | Patron |
| GET | `/resale-listings/{id}` | Read one ResaleListing including cap and settlement components | Patron, BoxOfficeAgent, SecurityInvestigator, VenueAdmin |
| GET | `/resale-listings` | List ResaleListings | Patron, BoxOfficeAgent, SecurityInvestigator, VenueAdmin |
| POST | `/resale-listings/{id}/purchase` | Buy a listed entitlement and split settlement | Patron |
| POST | `/resale-listings/{id}/delist` | Seller withdraws a listing | Patron |
| POST | `/credential-requests` | Draft a comp, will-call or credential distribution | BoxOfficeAgent |
| GET | `/credential-requests/{id}` | Read one CredentialRequest including approval identities | BoxOfficeAgent, TicketingApprover, SecurityInvestigator, VenueAdmin |
| GET | `/credential-requests` | List CredentialRequests | BoxOfficeAgent, TicketingApprover, SecurityInvestigator, VenueAdmin |
| POST | `/credential-requests/{id}/submit` | Submit a draft, or resubmit after requested changes | BoxOfficeAgent |
| POST | `/credential-requests/{id}/request-changes` | Return a submitted request for revision | TicketingApprover |
| POST | `/credential-requests/{id}/approve` | Approve the distribution and auto-issue its entitlements | TicketingApprover |
| POST | `/credential-requests/{id}/reject` | Reject the distribution | TicketingApprover |
| POST | `/scan-sessions` | Open a scanning session on a gate | GateOperator |
| GET | `/scan-sessions/{id}` | Read one ScanSession including its scan counters | GateOperator, SecurityInvestigator, VenueAdmin |
| GET | `/scan-sessions` | List ScanSessions | GateOperator, SecurityInvestigator, VenueAdmin |
| POST | `/scan-sessions/{id}/scan-events` | Adjudicate one live gate scan | GateOperator |
| POST | `/scan-sessions/{id}/offline-batch` | Upload a scanner's offline cache | GateOperator |
| POST | `/scan-sessions/{id}/close` | Close a scanning session | GateOperator |
| GET | `/scan-events/{id}` | Read one immutable ScanEvent | GateOperator, SecurityInvestigator, VenueAdmin |
| GET | `/scan-events` | List ScanEvents | GateOperator, SecurityInvestigator, VenueAdmin |
| GET | `/denied-entry-incidents/{id}` | Read one denied-entry incident | BoxOfficeAgent, SecurityInvestigator, VenueAdmin |
| GET | `/denied-entry-incidents` | List denied-entry incidents | BoxOfficeAgent, SecurityInvestigator, VenueAdmin |
| POST | `/denied-entry-incidents/{id}/start-review` | Take ownership of an OPEN incident | SecurityInvestigator |
| POST | `/denied-entry-incidents/{id}/remediate` | Grant goodwill remediation and close the incident | SecurityInvestigator |
| POST | `/denied-entry-incidents/{id}/dismiss` | Close the incident with no credit and withdraw the strike | SecurityInvestigator |
| POST | `/events/{id}/reconciliation-reports` | Cut a reconciliation report against reported attendance | VenueAdmin |
| GET | `/reconciliation-reports/{id}` | Read one reconciliation report | SecurityInvestigator, VenueAdmin |
| GET | `/reconciliation-reports` | List reconciliation reports | SecurityInvestigator, VenueAdmin |
| POST | `/reconciliation-reports/{id}/finalize` | Finalize the report and reconcile the event | VenueAdmin |
| POST | `/reconciliation-reports/{id}/reopen` | Reopen a finalized report for correction | VenueAdmin |

List endpoints accept `limit` and `offset` alongside their filters. Events filter by `status`. Access zones filter by `event_id`, `posture` and `required_entitlement_level`. Gates filter by `event_id`, `access_zone_id` and `status`. Patrons filter by `email` and `identity_verified`. Tickets filter by `event_id`, `access_zone_id`, `holder_patron_id`, `credential_request_id`, `lifecycle_status` and `admission_status`. Transfer requests filter by `ticket_id`, `from_patron_id`, `to_patron_id` and `status`. Resale listings filter by `ticket_id`, `seller_patron_id`, `buyer_patron_id`, `superseded_listing_id` and `status`. Credential requests filter by `event_id`, `access_zone_id`, `recipient_patron_id`, `status` and `distribution_type`. Scan sessions filter by `gate_id`, `status` and `mode`. Scan events filter by `scan_session_id`, `ticket_id`, `result`, `source` and `direction`. Denied-entry incidents filter by `scan_event_id`, `ticket_id`, `patron_id`, `category` and `status`. Reconciliation reports filter by `event_id` and `status`. The audit trail filters by `subject_type`, `subject_id` and `action`.

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_ZONE_NOT_FOUND` | 404 Not Found |
| `ERR_GATE_NOT_FOUND` | 404 Not Found |
| `ERR_PATRON_NOT_FOUND` | 404 Not Found |
| `ERR_TICKET_NOT_FOUND` | 404 Not Found |
| `ERR_TRANSFER_NOT_FOUND` | 404 Not Found |
| `ERR_LISTING_NOT_FOUND` | 404 Not Found |
| `ERR_CREDENTIAL_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_SCAN_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_INCIDENT_NOT_FOUND` | 404 Not Found |
| `ERR_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_CROSS_EVENT_REFERENCE` | 422 Unprocessable Entity |
| `ERR_NOT_TICKET_HOLDER` | 403 Forbidden |
| `ERR_STALE_TICKET_VERSION` | 412 Precondition Failed |
| `ERR_STALE_GATE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_EVENT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_TICKET_VOIDED` | 409 Conflict |
| `ERR_SESSION_NOT_OPEN` | 409 Conflict |
| `ERR_SESSION_NOT_OFFLINE_CAPABLE` | 409 Conflict |
| `ERR_EVENT_STATE_FORBIDS_OPERATION` | 409 Conflict |
| `ERR_EVENT_STATE_FORBIDS_TRANSFER` | 409 Conflict |
| `ERR_GATE_NOT_SCANNING` | 409 Conflict |
| `ERR_ZONE_FROZEN` | 409 Conflict |
| `ERR_EVENT_ALREADY_RECONCILED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_DUPLICATE_DEDUPE_KEY` | 409 Conflict |
| `ERR_COUNTERFEIT_BARCODE` | 422 Unprocessable Entity |
| `ERR_BARCODE_EPOCH_INVALID` | 422 Unprocessable Entity |
| `ERR_DEVICE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_SCAN` | 409 Conflict |
| `ERR_REENTRY_LOCKOUT` | 409 Conflict |
| `ERR_ZONE_NOT_ENTITLED` | 403 Forbidden |
| `ERR_ZONE_CAPACITY_FULL` | 409 Conflict |
| `ERR_EVENT_FIRE_CODE_FULL` | 409 Conflict |
| `ERR_PATRON_FRAUD_BLOCKED` | 403 Forbidden |
| `ERR_GATE_SESSION_OVERLAP` | 409 Conflict |
| `ERR_TRANSFER_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_ZONE_CREDENTIAL_WINDOW_CAPACITY` | 409 Conflict |
| `ERR_RECIPIENT_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_TICKET_NOT_TRANSFERABLE` | 422 Unprocessable Entity |
| `ERR_MARKETPLACE_NOT_VERIFIED` | 422 Unprocessable Entity |
| `ERR_PRICE_CAP_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SETTLEMENT_POOL_INSUFFICIENT` | 409 Conflict |
| `ERR_ATTENDANCE_VARIANCE_UNRESOLVED` | 409 Conflict |
| `ERR_DUPLICATE_CODE` | 409 Conflict |
| `ERR_DUPLICATE_EMAIL` | 409 Conflict |
| `ERR_MAX_REVISIONS_EXCEEDED` | 409 Conflict |
| `ERR_SELF_PURCHASE` | 422 Unprocessable Entity |
