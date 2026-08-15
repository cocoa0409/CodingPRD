# Citrus Packinghouse & Grove Caretaking API — Product Requirements Document

## 1. Introduction

A Florida citrus packinghouse sits at the junction of field and market. Fruit arrives by the truckload from grower-owned groves, is conditioned in degreening rooms, graded on the sort line, and sold into fresh and juice channels; the proceeds then flow back to growers through weekly variety pools. Around that core flow orbit two satellite businesses: a grove caretaking program (spray, fertilize, prune, mow) whose work is billed back to each grower, and an export program that must satisfy cold-treatment and phytosanitary protocol for Japan, the European Union, and Korea. This document specifies the Citrus Packinghouse API, the system of record for all of it — from the first maturity sample drawn in a block to the final settlement statement a grower receives.

Two design priorities shape every workflow that follows. First, compliance is not an afterthought: pest quarantine orders, delivery holds, and phytosanitary certificates gate every material movement, and regulatory posture is treated as derived data that is recomputed the moment any underlying fact changes. Second, money is reconciled continuously: pool prices exist in a forward-looking provisional form and an actuals-only final form, advances are recouped under two distinct policies, and caretaking charges offset settlement proceeds — all within a single atomic request boundary, so that no reader ever observes a half-applied cascade. Because several of these flows are deliberately split across two people (the sorter and the verifier, the quarantine issuer and the releasing officer, the inspection requester and the certificate issuer), the API also encodes segregation-of-duties rules as first-class constraints.

All endpoints are mounted under `/packinghouse`.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming their operational capacity. Seven roles are recognized, spelled exactly as follows: `PackinghouseAdmin`, `FieldSupervisor`, `QualityInspector`, `LineOperator`, `PoolAccountant`, `ComplianceOfficer`, and `Grower`. A request missing either header, or presenting an `X-User-Role` that names no declared role, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A caller whose role does not appear in the endpoint's authorized set is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The roles divide the work of the packinghouse along the following lines. A `PackinghouseAdmin` holds configuration authority: growers, groves, crews, degreening rooms, allocation channels, and the logical clock. A `FieldSupervisor` runs field operations: harvest crew scheduling, the harvest assignment lifecycle, fruit receiving, and caretaking scheduling and completion. A `QualityInspector` is the independent quality authority: maturity testing and sort-run verification. A `LineOperator` runs the packing line: degreening sessions, sort runs, and delivery close. A `PoolAccountant` owns grower accounting: pools, advances, settlement, caretaking invoicing, and grower standing. A `ComplianceOfficer` owns regulatory compliance: quarantine orders, delivery holds, export lots, and phytosanitary certificates — with segregation-of-duties rules applying within this role. A `Grower` is the grower-portal user: it reads its own resources, requests advances and caretaking services, and pays or disputes invoices.

When `X-User-Role` is `Grower`, `X-User-ID` is the `id` of the acting Grower record; ownership checks on any resource that references a grower compare the resource's grower reference — directly on advances and invoices, or through the owning grower of the target grove — to `X-User-ID`. A mismatch is rejected with `ERR_GROWER_OWNERSHIP_MISMATCH` (HTTP 403). The ownership-scoped operations are exactly: `GET /packinghouse/growers/{id}`, `POST /packinghouse/advances`, `POST /packinghouse/caretaking-orders`, `POST /packinghouse/caretaking-orders/{id}/cancel`, `POST /packinghouse/caretaking-invoices/{id}/payments`, and `POST /packinghouse/caretaking-invoices/{id}/dispute`. Beyond those, the Grower role's list and detail reads of its own groves, advances, caretaking orders, caretaking invoices, pools, and settlement statements are likewise scoped to resources it owns.

When `X-User-Role` is `PackinghouseAdmin`, `FieldSupervisor`, `QualityInspector`, `LineOperator`, `PoolAccountant`, or `ComplianceOfficer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where an audit trail demands — for example as `created_by` on a sort run, `verified_by` on a sort-run verification, `issued_by` and `released_by` on quarantine orders, `issued_by` on phytosanitary certificates, or `inspection_requested_by` on an export lot — but it never compares such an identifier to any entity's `id`.

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

List endpoints are paginated through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items skipped and defaults to 0. Unless an endpoint states otherwise, list responses are sorted by `created_at` in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Change Tracking

Every resource in this API carries a uniform set of system-managed properties: an `id` that is a server-minted UUID with no type prefix; a `created_at` timestamp recording creation; an `updated_at` timestamp refreshed on every modification; and a `version` integer that increments with every mutation of the resource. Both timestamps are ISO 8601 UTC values with three fractional digits. Mutations include system-driven changes, not just client-directed writes: when a cascade cancels an assignment, a recompute refreshes a derived field, or a posting bumps a pool's aggregates, each touched resource has its `updated_at` refreshed and its `version` incremented. This uniform change ledger is what makes the optimistic concurrency rules of §2.8 meaningful.

### 2.5. The Packinghouse Logical Clock

The server keeps a logical clock that is decoupled from wall-clock time. Before any client call has been made, the logical clock reads exactly 2026-08-01T00:00:00Z, and it never falls back to wall-clock time. A `PackinghouseAdmin`-only test-driving capability advances the clock by supplying a `to_iso8601` instant; the response reports the new `current_utc`. All timestamped logic — maturity test expiry, certificate expiry, degreening durations, harvest window gates, pool week membership, and every `created_at`-style stamp described as coming from the logical clock — reads this clock and no other.

### 2.6. The Request Gate Ladder

Every request is evaluated against a fixed ladder of validation tiers, and the ladder's order is part of the contract: a request that would fail checks in two different tiers is rejected with the error from the earlier tier, so a failure higher on the ladder is never masked by one lower down.

1. **Authentication** — the `X-User-ID` and `X-User-Role` headers are present and the role is one of the seven declared roles; otherwise `ERR_UNAUTHENTICATED` (HTTP 401). Applies to all endpoints.
2. **Role authorization** — the caller's role is listed among the endpoint's authorized roles; otherwise `ERR_FORBIDDEN_ROLE` (HTTP 403). Applies to all endpoints.
3. **Grower ownership** — for the grower-accessible operations enumerated in §2.1, the caller's `X-User-ID` must equal the owning grower's `id`; otherwise `ERR_GROWER_OWNERSHIP_MISMATCH` (HTTP 403).
4. **Existence** — every resource referenced in the path exists, validated left to right (§2.11); otherwise `ERR_NOT_FOUND` (HTTP 404). Applies to all endpoints.
5. **Request well-formedness** — required fields are present, types are valid, enum members are valid, and numeric ranges are respected; otherwise `ERR_INVALID_REQUEST` (HTTP 400). Applies to all endpoints.
6. **State legality** — the target resource's current state permits the requested transition, including terminal-state lockdown; optimistic-concurrency version mismatches are also evaluated at this tier and surface as `ERR_STALE_VERSION` (HTTP 412), while other state violations surface as `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Applies to all action endpoints.
7. **Regulatory and safety gates** — grove quarantine posture must be `CLEAR` where required (`ERR_GROVE_QUARANTINED`), the grove must be `PRODUCTIVE` (`ERR_GROVE_RETIRED`), a delivery's regulatory status must not be `HELD` or `CONDEMNED` where required (`ERR_DELIVERY_REGULATORY_HOLD`), and segregation-of-duties identity pairs must differ (`ERR_SEGREGATION_OF_DUTIES`). The export-protocol gates `ERR_COLD_TREATMENT_INSUFFICIENT` and `ERR_FRUIT_FLY_PROTOCOL_BLOCK` also live in this tier, and for JAPAN-bound export-lot transitions the fruit-fly protocol check is evaluated before the generic quarantine-posture check, so a lot blocked on both surfaces `ERR_FRUIT_FLY_PROTOCOL_BLOCK`. This tier guards: assignment creation and start, delivery creation, degreening session creation and release, export-lot creation, inspection requests, certification, quarantine release, certificate creation, and sort-run verification.
8. **Maturity gates** — the grove has a `CURRENT` maturity test (`ERR_MATURITY_TEST_REQUIRED`) and that test's result is `PASS` (`ERR_MATURITY_NOT_PASSING`), in that relative order. Applies to assignment start and delivery creation.
9. **Uniqueness and set constraints** — human-readable codes and the pool's variety-week pair are unique (`ERR_DUPLICATE_ENTITY`), and at most one non-`VOIDED` sort run exists per delivery (`ERR_SORT_RUN_ALREADY_ACTIVE`). Applies to create endpoints.
10. **Capacity constraints** — crew window capacity (`ERR_CREW_CAPACITY_EXCEEDED`), crew window overlap (`ERR_CREW_WINDOW_OVERLAP`), room aggregate capacity (`ERR_ROOM_CAPACITY_EXCEEDED`), the sort grade sum (`ERR_SORT_BOX_MISMATCH`), export-lot channel availability (`ERR_CHANNEL_CAPACITY_EXCEEDED`), acres treated (`ERR_ACRES_EXCEED_GROVE`), and chemical cost on a non-spray order (`ERR_CHEMICAL_COST_NOT_ALLOWED`). Applies to create and complete endpoints with quantity semantics.
11. **Temporal gates** — maturity test unexpired (`ERR_MATURITY_TEST_EXPIRED`), assignment window open (`ERR_ASSIGNMENT_WINDOW_NOT_OPEN`), degreening duration within bounds (`ERR_DEGREENING_DURATION_OUT_OF_BOUNDS`), and certificate unexpired at ship time (`ERR_CERT_EXPIRED`). Applies to time-gated action endpoints. Note the interaction with tier 8: a grove with no `CURRENT` test surfaces `ERR_MATURITY_TEST_REQUIRED`, one whose `CURRENT` test failed surfaces `ERR_MATURITY_NOT_PASSING`, and only then does an expired passing test surface `ERR_MATURITY_TEST_EXPIRED`.
12. **Fiscal gates** — grower standing where value is extended (`ERR_GROWER_NOT_ACTIVE`), the advance cap (`ERR_ADVANCE_CAP_EXCEEDED`), and invoice payment bounds (`ERR_PAYMENT_AMOUNT_INVALID`, `ERR_INVOICE_OVERPAYMENT`). Applies to advance approval, delivery creation, caretaking order creation, and invoice payments.
13. **Referential coherence** — channel variety, market, and week match the referencing entity (`ERR_CHANNEL_MISMATCH`), the referenced assignment is `IN_PROGRESS` and grove-consistent (`ERR_ASSIGNMENT_NOT_ACTIVE`), a juice channel exists where posting or diversion requires one (`ERR_NO_JUICE_CHANNEL`), the grove is enrolled for caretaking (`ERR_CARETAKING_NOT_ENROLLED`), a degreening-required variety has completed degreening (`ERR_DEGREENING_REQUIRED`), and the pool is in the state the operation pins (`ERR_POOL_NOT_ACCEPTING`). Applies to endpoints with cross-referenced entities.

### 2.7. Cents, Ratios and Rounding Discipline

All monetary amounts in this API — prices, proceeds, balances, advances, invoice totals — are carried as integer cents; there are no fractional cents anywhere in the system. Where a computed monetary value arises from division or from a percentage of another amount, it is rounded half-up to whole cents. Two non-monetary measurements carry finer precision: a maturity test's `ratio` and a sort run's `ge_boxes` are stored at exactly 2 decimal places, rounded half-up, as is a degreening session's `duration_hours`. Wherever this document says a value is "rounded half-up", a fraction of exactly one half rounds away from zero. Rounding order is pinned wherever several rounded quantities feed a larger total: components are rounded first and summed second, never the reverse.

### 2.8. Optimistic Concurrency Control

Three write operations perform create-with-supersede or repricing semantics against a parent entity whose `version` they themselves advance, and each therefore requires the caller to prove it has observed the parent's current state:

- Recording a new maturity test for a grove requires `expected_grove_version` in the request, carrying the caller's last observed `version` of that grove. Because the create supersedes the grove's `CURRENT` test and bumps the grove's `version`, a request whose `expected_grove_version` is behind the grove's current `version` — for example because another writer has just recorded a test that legitimately superseded the one the caller saw — is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than silently superseding a test the caller never observed.
- Creating a sort run requires `expected_delivery_version` matching the delivery's current `version`. After a prior run is voided, a new run legitimately replaces it, and the create bumps the delivery's `version`; a create carrying a stale `expected_delivery_version` is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Setting or re-setting a pool's final price requires `expected_pool_version` matching the pool's current `version`; a request whose value is behind — for example because a re-price landed after the caller's read — is rejected with `ERR_STALE_VERSION` (HTTP 412).

The version field is non-optional on exactly these three operations. Endpoints not listed here do not take a version field at all.

### 2.9. Segregation of Duties

Three workflows are deliberately split so that no single operator can carry them end to end, and the enforcement is by identity, not by role. A sort run's verifier must differ from its creator: the `X-User-ID` recorded as `verified_by` may not equal the run's `created_by`. A quarantine order's releasing officer must differ from its issuing officer: `released_by` may not equal `issued_by`. And the officer who records the inspection result and issues a phytosanitary certificate for an export lot must differ from the officer who requested the inspection: the certificate's `issued_by` may not equal the lot's `inspection_requested_by`. Every violation of these pairings is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403).

### 2.10. Quarantine Posture and the Delivery's Two Status Dimensions

A grove's `quarantine_posture` is never written directly; it is a computed signal. A grove is `QUARANTINED` if and only if at least one `ACTIVE` quarantine order covers it — either an order scoped `GROVE` whose grove reference matches, or an order scoped `COUNTY_ZONE` whose `county_code` matches the grove's county — and `CLEAR` otherwise. Every quarantine order creation or release recomputes the posture of every affected grove within the same request.

Deliveries carry two independent status dimensions on the same row: `processing_status` tracks the fruit's physical progress (`RECEIVED`, `IN_DEGREENING`, `READY_TO_SORT`, `SORTED`, `CLOSED`), while `regulatory_status` tracks its compliance standing (`CLEAR`, `HELD`, `RELEASED`, `CONDEMNED`). The two evolve in parallel and are guarded independently; several operations require a specific combination of both. A `CONDEMNED` delivery is terminally condemned, and a `CLOSED` delivery is terminally processed.

### 2.11. Nested Resource Retrieval

Where an endpoint path contains more than one resource identifier — a maturity test under a grove, a phytosanitary certificate under an export lot — the system validates the existence of each identifier in left-to-right order and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not correspond to an existing resource, without examining later segments. A request for certificates under a non-existent export lot therefore fails on the lot before any certificate lookup is attempted.

## 3. Business Logic & Workflows

### 3.1. Growers, Groves and Fiscal Standing

A `PackinghouseAdmin` onboards a grower by supplying a `grower_code` — a human-readable code that must be unique across all growers — and a `display_name`. The new grower's `status` begins as `ACTIVE`, and two computed ledgers begin at zero: `advance_outstanding_cents`, which always equals the sum of `outstanding_cents` over the grower's advances in `ISSUED` or `PARTIALLY_RECOUPED` status, and `caretaking_balance_cents`, which always equals the sum of each invoice's `total_cents` minus its `paid_cents` over the grower's invoices in `ISSUED` or `PARTIALLY_PAID` status. Growers can be listed with an optional `status` filter, and any single grower record can be read — by staff roles, or by the `Grower` role reading its own `id`.

Grower standing is a fiscal gate, managed by a `PoolAccountant`. Suspending moves a grower `ACTIVE` → `SUSPENDED`, and while suspended the grower is barred from new value-extending activity: new advances, new deliveries, and new caretaking orders are all refused. Reinstating moves `SUSPENDED` → `ACTIVE`. Termination moves a grower from either `ACTIVE` or `SUSPENDED` to `TERMINATED`, which is terminal, and is permitted only when both ledgers are clean — `advance_outstanding_cents` is zero and `caretaking_balance_cents` is zero; if either balance remains, the termination is refused with `ERR_GROWER_NOT_ACTIVE`. Terminating a grower also cancels every caretaking service order of the grower's groves that is still in `REQUESTED` or `SCHEDULED` status. More generally, any value-extending operation attempted for a grower that is `SUSPENDED` or `TERMINATED` fails with `ERR_GROWER_NOT_ACTIVE` (HTTP 409).

Groves are registered under an owning grower. Registration takes the `grower_id` of the owner, a `block_code` that must be unique within that grower's groves, a `variety` of `HAMLIN`, `VALENCIA`, `RED_GRAPEFRUIT`, or `TANGERINE`, an `acreage` greater than zero, a `county_code` naming the Florida county (for example POLK or HIGHLANDS), and an optional `caretaking_enrolled` flag that defaults to false. A grove's `lifecycle_status` begins as `PRODUCTIVE`, and its `quarantine_posture` — the computed signal defined in §2.10 — begins as `CLEAR`. The grove collection can be filtered by `grower_id`, `variety`, `quarantine_posture`, or `lifecycle_status`; a `Grower` caller sees only its own groves.

Retiring a grove, a `PackinghouseAdmin` action, moves `lifecycle_status` from `PRODUCTIVE` to the terminal `RETIRED`. Retirement is refused with `ERR_INVALID_STATE_TRANSITION` while the grove has any harvest assignment in `SCHEDULED` or `IN_PROGRESS`, or any delivery whose `processing_status` is `RECEIVED`, `IN_DEGREENING`, or `READY_TO_SORT`. When retirement succeeds, every caretaking service order of the grove in `REQUESTED` or `SCHEDULED` status is cancelled, and the grove's `version` increments. From then on the grove accepts no new harvest assignments, deliveries, or caretaking orders: attempts against a `RETIRED` grove fail with `ERR_GROVE_RETIRED` (HTTP 409).

### 3.2. Maturity Testing and Harvest Scheduling

Before any fruit may move, the grove must prove maturity. A `QualityInspector` records a maturity test for a grove by supplying `sampled_at` (the UTC instant the sample was drawn), `brix` in degrees Brix, `acid_pct` (percent anhydrous citric acid), and `juice_pct` (percent juice content by weight). The measurements must be well-formed — `brix` and `acid_pct` greater than zero, `juice_pct` greater than zero and at most 100 — or the request fails with `ERR_INVALID_REQUEST`. Because recording a test supersedes the grove's current test, the request must also carry `expected_grove_version` per the optimistic-concurrency rule of §2.8, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412).

From these inputs the system derives the rest. The `ratio` is `brix` divided by `acid_pct`, rounded half-up to 2 decimal places — the rounding happens first, and every comparison below applies to the rounded ratio. The `result` is `PASS` when all three variety minimums are met: the rounded ratio is at least the variety's minimum ratio, `brix` is at least the minimum Brix, and `juice_pct` is at least the minimum juice percent; otherwise it is `FAIL`. The minimums are: for `HAMLIN`, ratio 9.0, Brix 8.5, juice 42.0; for `VALENCIA`, ratio 9.0, Brix 9.0, juice 45.0; for `RED_GRAPEFRUIT`, ratio 7.0, Brix 8.0, juice 38.0; and for `TANGERINE`, ratio 9.5, Brix 9.0, juice 40.0. The test's `expires_at` is exactly `sampled_at` plus 120 hours — five full days. A test's `status` is `CURRENT` for the newest test of the grove; creating a newer test atomically moves the prior `CURRENT` test to `SUPERSEDED` (its terminal state) and increments the grove's `version`. Usability is time-derived rather than stored: a test is usable for harvest and receiving exactly while its `status` is `CURRENT`, its `result` is `PASS`, and the logical clock reads strictly before `expires_at` — at the expiry instant itself the test is no longer usable, and there is no stored expired state. A grove's tests can be listed newest first (this listing overrides the default ascending sort), and any single test can be read by its `id`.

Harvest capacity is modeled through crews. A `PackinghouseAdmin` registers a crew with a unique `crew_code` and a `daily_capacity_boxes` greater than zero; the crew begins `ACTIVE`. Deactivation moves a crew `ACTIVE` → `INACTIVE` (terminal) and is refused with `ERR_INVALID_STATE_TRANSITION` while the crew holds any assignment in `SCHEDULED` or `IN_PROGRESS`. Any attempt to engage an `INACTIVE` crew — at scheduling or at start — is refused with `ERR_CREW_NOT_ACTIVE`. Crews can be listed with a `status` filter.

A `FieldSupervisor` schedules a crew onto a grove by creating a harvest assignment with `crew_id`, `grove_id`, a `window_start` (inclusive) and `window_end` (exclusive) forming a half-open UTC window, and `planned_boxes` greater than zero. Two independent checks guard crew capacity at creation. The capacity check: the window's length in hours divided by 24 and rounded up to whole days — so a 25-hour window counts as two days — multiplied by the crew's `daily_capacity_boxes` gives the window capacity, and `planned_boxes` may not exceed it, though an exact fit is allowed; a violation fails with `ERR_CREW_CAPACITY_EXCEEDED`. The overlap check: the new window is compared against the crew's existing `SCHEDULED` and `IN_PROGRESS` assignments, and a conflict exists exactly when the new window's start falls before an existing window's end and that existing window's start falls before the new window's end; windows that merely touch — the new one starting at the instant an existing one ends — do not conflict. A conflicting request fails with `ERR_CREW_WINDOW_OVERLAP`. The target grove must also be `PRODUCTIVE` (`ERR_GROVE_RETIRED`) and `CLEAR` of quarantine (`ERR_GROVE_QUARANTINED`). A new assignment is born `SCHEDULED`, with `actual_boxes` null until completion; the assignment collection can be filtered by `crew_id`, `grove_id`, or `status`.

Starting an assignment, a `FieldSupervisor` action, moves it `SCHEDULED` → `IN_PROGRESS` and re-verifies the full gate set at start time: the crew is still `ACTIVE` (`ERR_CREW_NOT_ACTIVE`), the grove is `PRODUCTIVE` (`ERR_GROVE_RETIRED`) and `CLEAR` (`ERR_GROVE_QUARANTINED`), the grove has a `CURRENT` maturity test (`ERR_MATURITY_TEST_REQUIRED`) whose `result` is `PASS` (`ERR_MATURITY_NOT_PASSING`) and which has not expired (`ERR_MATURITY_TEST_EXPIRED`), and the logical clock reads within the assignment's window — at or after `window_start` and strictly before `window_end`, with an attempt outside that half-open window rejected as `ERR_ASSIGNMENT_WINDOW_NOT_OPEN`.

Completing an assignment moves `IN_PROGRESS` → `COMPLETED` and records `actual_boxes`, which must be at least 1 and at most the planned boxes multiplied by 1.25 and rounded up to a whole box; a count outside that band is rejected with `ERR_INVALID_REQUEST`. Cancellation moves an assignment to the terminal `CANCELLED`: from `SCHEDULED` a `FieldSupervisor` may cancel freely, and the system cancels scheduled assignments on its own during the quarantine cascade (§3.8) and on grove retirement; from `IN_PROGRESS` cancellation is allowed only while no delivery references the assignment, and otherwise fails with `ERR_INVALID_STATE_TRANSITION`. Either way, cancelling releases the crew's committed window capacity and the derived crew load is recomputed.

### 3.3. Receiving Fruit: Deliveries and Pool Resolution

When a truck arrives, a `FieldSupervisor` receives the load by creating a delivery with `grove_id`, `assignment_id`, `gross_boxes` greater than zero, and `tare_boxes` — the reject-at-scale count — which must be zero or more and strictly fewer than `gross_boxes` (`ERR_INVALID_REQUEST` otherwise). The system stamps `received_at` from the logical clock, copies `variety` from the grove at creation, computes `net_boxes` as `gross_boxes` minus `tare_boxes`, and resolves `pool_id` to the `OPEN` pool whose variety matches and whose week — the seven dates from the pool's `week_start` through six days later, inclusive — contains `received_at`. If no such `OPEN` pool exists, receiving fails with `ERR_POOL_NOT_ACCEPTING`.

Receiving is gated on the full standing of the source. The grower must be `ACTIVE` (`ERR_GROWER_NOT_ACTIVE`); the grove must be `PRODUCTIVE` (`ERR_GROVE_RETIRED`) and `CLEAR` of quarantine (`ERR_GROVE_QUARANTINED`); the grove must have a `CURRENT` maturity test (`ERR_MATURITY_TEST_REQUIRED`) whose `result` is `PASS` (`ERR_MATURITY_NOT_PASSING`) and which is unexpired (`ERR_MATURITY_TEST_EXPIRED`); and the referenced assignment must be `IN_PROGRESS` and belong to the same grove as the delivery (`ERR_ASSIGNMENT_NOT_ACTIVE`). A delivery is born with `processing_status` `RECEIVED` and `regulatory_status` `CLEAR`, and its `requires_degreening` flag is derived from the variety: true for `RED_GRAPEFRUIT` and `TANGERINE`, false for `HAMLIN` and `VALENCIA`. The delivery collection can be filtered by `grove_id`, `assignment_id`, `pool_id`, `processing_status`, or `regulatory_status`.

Regulatory control of a delivery rests with a `ComplianceOfficer`. Placing a hold moves the regulatory dimension `CLEAR` → `HELD`, and while a delivery is `HELD` its sort runs cannot be created, verified, or posted — those operations fail with `ERR_DELIVERY_REGULATORY_HOLD`. Releasing moves `HELD` → `RELEASED`. Condemning moves `HELD` → the terminal `CONDEMNED`, and is permitted only while the delivery's processing dimension is neither `SORTED` nor `CLOSED`; condemnation auto-voids any sort run of the delivery that is `OPEN` or `VERIFIED`, and that auto-void does not touch pool totals — only `POSTED` runs contribute to the pool — but it does recompute the delivery's sortable state. The quarantine cascade of §3.8 can also drive deliveries into `HELD`, and a quarantine release can return them to `RELEASED` when no other hold cause remains. Any attempt to perform a sorting operation against a `HELD` or `CONDEMNED` delivery fails with `ERR_DELIVERY_REGULATORY_HOLD` (HTTP 422).

Closing is the packing line's last word on a delivery: a `LineOperator` moves a `SORTED` delivery to the terminal `CLOSED` once the delivery's pool has been priced — that is, the pool is in `PRICED` or `SETTLED`; while the pool is still in an earlier state the close fails with `ERR_POOL_NOT_ACCEPTING`. Each of these delivery mutations refreshes the delivery's `updated_at` and increments its `version`.

### 3.4. Degreening Rooms and Conditioning Sessions

Degreening — conditioning with ethylene, optionally with color-add dye — happens in rooms configured by a `PackinghouseAdmin`. A room is registered with a unique `room_code`, a `capacity_boxes` greater than zero, and optional `min_hours` and `max_hours` bounding conditioning duration, defaulting to 12 and 72 hours respectively. A room begins `AVAILABLE`. Taking a room out of service moves it `AVAILABLE` → `MAINTENANCE` and is refused with `ERR_ROOM_NOT_AVAILABLE` while any session in the room is still `CONDITIONING`; returning it moves `MAINTENANCE` → `AVAILABLE`. Loading fruit into a room that is in `MAINTENANCE` likewise fails with `ERR_ROOM_NOT_AVAILABLE`. Rooms can be listed with a `status` filter.

A `LineOperator` loads fruit by creating a degreening session with `room_id`, `delivery_id`, `boxes` greater than zero, `planned_hours` greater than zero, and an optional `color_add_applied` flag that defaults to true — when applied, the fruit receives the color-add treatment of ethylene plus dye. The system stamps `started_at` from the logical clock, and the session reserves the half-open interval from `started_at` through `started_at` plus `planned_hours`. Two quantity rules apply: the boxes across all of a delivery's sessions may never sum beyond the delivery's `net_boxes` (`ERR_INVALID_REQUEST`), and the room's aggregate capacity may never be exceeded (`ERR_ROOM_CAPACITY_EXCEEDED`). The capacity check has aggregate semantics, unlike the crew's exclusive occupancy: the new session is rejected if and only if there exists some instant within its reserved interval at which the boxes of all still-`CONDITIONING` sessions whose reserved intervals cover that instant, plus the new session's `boxes`, would exceed the room's `capacity_boxes`; equality at every instant is permitted, and sessions in `RELEASED` or `ABORTED` never occupy capacity. The first session created for a delivery moves the delivery's processing dimension `RECEIVED` → `IN_DEGREENING` and bumps the delivery's `version`. A session is born `CONDITIONING`, with `released_at` and `duration_hours` null. Sessions can be listed with `room_id`, `delivery_id`, or `status` filters.

Releasing a session moves it `CONDITIONING` → `RELEASED`. A `LineOperator` may release within bounds; a `QualityInspector` may release with `override_approved` set true to override the duration bounds. At release the system stamps `released_at` from the logical clock and computes `duration_hours` — the elapsed hours between `started_at` and `released_at`, at 2 decimal places. The duration must lie within the room's `min_hours` to `max_hours`, both bounds inclusive, unless a `QualityInspector` supplies the override; an out-of-bounds release without it fails with `ERR_DEGREENING_DURATION_OUT_OF_BOUNDS`. The delivery's regulatory status must also be `CLEAR` or `RELEASED` (`ERR_DELIVERY_REGULATORY_HOLD`). When the released plus aborted boxes of a delivery reach its `net_boxes`, the delivery's processing advances `IN_DEGREENING` → `READY_TO_SORT` with a version bump.

Aborting, a `LineOperator` action, moves a session `CONDITIONING` → `ABORTED`. Aborted boxes still count toward the delivery's degreening completion — the fruit proceeds to sorting without color add — so an abort can be the event that advances the delivery to `READY_TO_SORT`. Both `RELEASED` and `ABORTED` are terminal for the session.

### 3.5. Sort Runs, Grading and the Packout Waterfall

Once fruit is ready, a `LineOperator` records a sort run against a delivery, supplying `delivery_id`, the measured outturn `fancy_boxes`, `choice_boxes`, `standard_boxes`, `juice_boxes`, and `cull_boxes` — each zero or more — plus a `color_score` (a whole number from 1, fully green, to 10, full color) and a `defect_pct` (the surface defect percentage of the grade sample, from 0 to 100). Because creating a run is the delivery's create-with-supersede operation, the request must carry `expected_delivery_version` per §2.8, and a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). The five grade counts must sum exactly to the delivery's `net_boxes`; any mismatch fails with `ERR_SORT_BOX_MISMATCH`. At most one non-`VOIDED` run may exist per delivery — a second live run is refused with `ERR_SORT_RUN_ALREADY_ACTIVE` — and uniqueness violations of any kind surface as `ERR_DUPLICATE_ENTITY`. The delivery's processing dimension must be `RECEIVED` or `READY_TO_SORT` and its regulatory dimension `CLEAR` or `RELEASED` (`ERR_DELIVERY_REGULATORY_HOLD`); if the delivery's variety requires degreening and the delivery is still sitting in `RECEIVED`, the run is refused with `ERR_DEGREENING_REQUIRED`. The creator's `X-User-ID` is stamped as `created_by`; the run is born `OPEN` with `verified_by`, `proceeds_cents`, and `allocation` all null. When the delivery's variety does not require degreening, creating the run also moves the delivery `RECEIVED` → `READY_TO_SORT` and bumps the delivery's `version`.

Two derived values are computed from the measurements. The `fresh_eligible` flag is true exactly when `color_score` is at least 6, `defect_pct` is at most 20, and the delivery's regulatory status is `CLEAR` or `RELEASED`. The `ge_boxes` value — grade-equivalent boxes — is `fancy_boxes` times 1.15, plus `choice_boxes` times 1.0, plus `standard_boxes` times 0.9, plus `juice_boxes` times 0.35, with the sum rounded half-up to 2 decimal places; cull boxes contribute zero and never enter the grade-equivalent total, and the weights apply to the measured grades regardless of where the fruit is finally sold. The value is computed at creation and stored again at post.

Verification is the first segregation-of-duties gate on the line: a `QualityInspector` moves a run `OPEN` → `VERIFIED`, and the verifier's `X-User-ID` must differ from the run's `created_by`, or the verification fails with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The delivery's regulatory status must be `CLEAR` or `RELEASED` (`ERR_DELIVERY_REGULATORY_HOLD`). Verification stamps `verified_by`.

Posting, a `LineOperator` action, moves a `VERIFIED` run to the terminal `POSTED` and is the moment money moves. Posting requires the delivery's regulatory status to be `CLEAR` or `RELEASED` (`ERR_DELIVERY_REGULATORY_HOLD`), the delivery's processing status to be exactly `READY_TO_SORT` (`ERR_INVALID_STATE_TRANSITION`), and the delivery's pool to be `OPEN` (`ERR_POOL_NOT_ACCEPTING`). A successful post runs the packout waterfall described below, stores the resulting `allocation` — an array of lines, each naming a channel, a grade, and a box count — together with `ge_boxes` and `proceeds_cents` on the run, moves the delivery `READY_TO_SORT` → `SORTED` with a version bump, decrements `remaining_boxes` on every channel the waterfall touched, and increases the pool's `posted_ge_boxes`, `posted_proceeds_cents`, and `sorted_field_boxes`, recomputes the pool's provisional price, and bumps the pool's `version`.

The packout waterfall works as follows. The channels considered are those matching the delivery's variety and the pool's week. When the run is fresh-eligible, the non-juice channels are walked in `priority_rank` ascending with ties broken by `created_at` ascending; within each channel, grades are filled in the fixed order `FANCY`, then `CHOICE`, then `STANDARD`; when the channel's `accepts_grades` includes the grade and its `remaining_boxes` is positive, the run places the lesser of that grade's unplaced boxes and the channel's remaining capacity — an exact fit is allowed — and both the unplaced count and the channel's remaining capacity are reduced by the amount placed. Whatever fresh fruit no channel could take overflows to juice. When the run is not fresh-eligible, the entire fancy, choice, and standard volume is forced into the juice channel at the juice price and the non-juice channels are left untouched. In both variants, the juice channel for the variety and week — which must exist, or the post fails with `ERR_NO_JUICE_CHANNEL` — receives the fresh overflow plus all measured `juice_boxes`; `cull_boxes` earn no proceeds and go to no channel. The run's `proceeds_cents` is the sum over the allocation lines of each line's boxes multiplied by its channel's `price_cents_per_box`. A channel's `remaining_boxes` is its `allocation_boxes` minus the boxes already allocated to `POSTED` runs; juice channels are uncapped and report null for `remaining_boxes`.

Two compensating actions exist. A `LineOperator` may void a run while it is `OPEN` or `VERIFIED`, moving it to the terminal `VOIDED`; the delivery-condemn cascade of §3.3 voids runs in those same two states. A `PoolAccountant` may reverse a `POSTED` run — moving it `POSTED` → `VOIDED` — only while the delivery's pool is `OPEN` or `INTAKE_CLOSED` (`ERR_POOL_NOT_ACCEPTING` once it has moved on). Reversal is exact: every touched channel's `remaining_boxes` is restored, the pool's `posted_ge_boxes`, `posted_proceeds_cents`, and `sorted_field_boxes` are decremented by exactly the amounts the post added, the provisional price is recomputed and the pool's `version` bumps, and the delivery returns `SORTED` → `READY_TO_SORT` with a version bump. Sort runs can be listed with `delivery_id` or `status` filters.

The waterfall is fed by channels configured by a `PackinghouseAdmin`. A channel is registered with a unique `channel_code`; a `channel_type` of `EXPORT`, `DOMESTIC_FRESH`, or `JUICE`; a `destination_market` — which must be `JAPAN`, `EU`, or `KOREA` for an `EXPORT` channel, `DOMESTIC` for a `DOMESTIC_FRESH` channel, and `NONE` for a `JUICE` channel, with an inconsistent pairing rejected as `ERR_INVALID_REQUEST`; a `variety` — the channel accepts only that variety; a `week_start` giving the Monday date, in YYYY-MM-DD form, of the allocation week; an `allocation_boxes` of zero or more giving the contracted weekly capacity — juice channels are uncapped and this value is ignored for them, conventionally 0; a `price_cents_per_box` greater than zero, the contract price paid into the pool per box; a `priority_rank` establishing waterfall order, lower filling first with ties broken by `created_at` ascending; and `accepts_grades`, a subset of `FANCY`, `CHOICE`, `STANDARD`, and `JUICE`. Channels can be listed with `variety`, `week_start`, or `channel_type` filters.

### 3.6. Pool Accounting, Advances and Weekly Settlement

A `PoolAccountant` opens a weekly pool by supplying a `variety` and a `week_start` — the Monday date in YYYY-MM-DD form; the pair of variety and week must be unique (`ERR_DUPLICATE_ENTITY`). The pool covers the seven-day span from `week_start` through six days later, inclusive, and is born `OPEN` with `posted_ge_boxes`, `posted_proceeds_cents`, and `sorted_field_boxes` all zero, `provisional_price_cents_per_ge_box` reading zero until proceeds and channel capacity exist, and `final_price_cents_per_ge_box` null. These aggregates are maintained by posting activity: `posted_ge_boxes` sums `ge_boxes` over the pool's deliveries' `POSTED` sort runs at 2 decimal places, `posted_proceeds_cents` sums `proceeds_cents` over `POSTED` runs plus export diversion credits and minus reversal debits, and `sorted_field_boxes` sums the `net_boxes` of deliveries with a `POSTED` run in the pool. Pools can be listed with `variety` or `status` filters, and the `Grower` role may read pools.

While a pool is `OPEN` or `INTAKE_CLOSED`, it quotes a forward-looking `provisional_price_cents_per_ge_box`, used for advance caps and grower estimates and readable at any time. The field is a stored value, not a figure derived at read time: born zero, it is recomputed at exactly these three moments — a sort-run post, a sort-run reverse, an export-lot diversion — and at no other time; in particular, registering an allocation channel for the pool's variety and week does not refresh any pool's provisional price. The projection considers the pool's finite-capacity channels, meaning its non-juice channels for the pool's variety and week: projected proceeds are the pool's `posted_proceeds_cents` plus eighty percent of the sum, over those channels, of each channel's `remaining_boxes` multiplied by its `price_cents_per_box`; projected grade-equivalent boxes are the pool's `posted_ge_boxes` plus eighty percent of the sum of those channels' `remaining_boxes`; and the provisional price is the projected proceeds divided by the larger of the projected grade-equivalent boxes and 1, rounded half-up to whole cents. Juice channels, being uncapped, are excluded from the projection.

Closing intake moves the pool `OPEN` → `INTAKE_CLOSED` and requires that no delivery assigned to the pool remains unfinished: a delivery with `processing_status` `RECEIVED`, `IN_DEGREENING`, or `READY_TO_SORT` and a regulatory status other than `CONDEMNED` blocks the close with `ERR_POOL_HAS_OPEN_DELIVERIES`. Setting the price moves `INTAKE_CLOSED` → `PRICED`, and may be repeated as a re-price `PRICED` → `PRICED`; both forms carry `expected_pool_version` per §2.8, rejected as stale with `ERR_STALE_VERSION`. Pricing uses actuals only — no fill projection — and computes a tiered packing charge keyed on the pool's total `sorted_field_boxes`: 150 cents per box when the total is below 10,000; 140 cents per box when it is at least 10,000 and below 50,000; and 125 cents per box when it is at least 50,000 — the tier edges include their lower bound. The packing charge total is `sorted_field_boxes` multiplied by the applicable rate, and the `final_price_cents_per_ge_box` is the pool's `posted_proceeds_cents` minus that packing charge, divided by the larger of `posted_ge_boxes` and 1, rounded half-up to whole cents. Each set-price bumps the pool's `version`.

Settlement moves the pool `PRICED` → the terminal `SETTLED` and runs the settlement waterfall once per grower with posted grade-equivalent boxes in the pool, processing growers in order of their `created_at`, oldest first. The four steps per grower are pinned in order because the terms are mutually dependent. Step one: the grower's share is the grower's posted grade-equivalent boxes in this pool multiplied by `final_price_cents_per_ge_box`, rounded half-up to whole cents. Step two: the caretaking offset is the lesser of the grower's `caretaking_balance_cents` and one half of the share rounded half-up to whole cents. Step three: the residual — the share minus the offset — is applied to recoup the grower's advances on this pool that stand in `ISSUED` or `PARTIALLY_RECOUPED`, taken oldest `issued_at` first with ties broken by `created_at` ascending; for each advance, a `NEXT_SETTLEMENT_FULL` policy caps recoupment at the advance's entire `outstanding_cents`, while a `PRO_RATA_THIRDS` policy caps it at one third of the advance's `amount_cents` rounded half-up to whole cents, and the amount actually recouped is the smallest of the advance's outstanding balance, its policy cap, and the remaining residual — with identical inputs, a pro-rata advance therefore yields a smaller recoupment and a larger grower payment than a full-recoupment advance; the residual falls by the recouped amount and the advance's `recouped_cents` rises by it, an advance recouped in full becomes `RECOUPED`, and one recouped in part becomes `PARTIALLY_RECOUPED`. Step four: whatever residual remains is the grower's payment. Across the settlement, each grower's `caretaking_balance_cents` falls by the applied offset and `advance_outstanding_cents` falls by the total recouped, and every touched grower's `version` increments. The per-grower settlement statements of a pool — share, offset, recoupment, and amount paid — are readable by a `PackinghouseAdmin`, a `PoolAccountant`, and the `Grower` for its own statement.

Advances let a grower draw against a pool before settlement. A `Grower` — for its own `grower_id` only — or a `PoolAccountant` requests one with `grower_id`, `pool_id`, an `amount_cents` greater than zero, and an optional `recoup_policy` of `NEXT_SETTLEMENT_FULL` or `PRO_RATA_THIRDS` that defaults to `NEXT_SETTLEMENT_FULL`. The advance is born `REQUESTED` with `issued_at` null and `recouped_cents` and `written_off_cents` zero, so `outstanding_cents` equals `amount_cents`; the invariant that the amount always equals the sum of recouped, written-off, and outstanding portions holds for the advance's entire life. Approval by a `PoolAccountant` moves `REQUESTED` → `ISSUED` and enforces three gates: the grower is `ACTIVE` (`ERR_GROWER_NOT_ACTIVE`), the pool is `OPEN` (`ERR_POOL_NOT_ACCEPTING`), and the advance-cap check passes. The cap is computed from the grower's posted position in that pool: take the `ge_boxes` of `POSTED` sort runs whose deliveries came from the grower's groves and were assigned to the advance's pool, multiply by the pool's current `provisional_price_cents_per_ge_box` to get the projected value, and take sixty percent of that value, rounded half-up to whole cents. Approval is allowed exactly when the grower's `advance_outstanding_cents` plus the new `amount_cents` is at most the cap — the boundary is inclusive — and otherwise fails with `ERR_ADVANCE_CAP_EXCEEDED`. A successful approval stamps `issued_at` from the logical clock, raises the grower's `advance_outstanding_cents` by `amount_cents`, and bumps the grower's `version`. Denial moves `REQUESTED` → the terminal `DENIED` with no further effect.

After issuance, settlement drives recoupment automatically as described above: `ISSUED` → `PARTIALLY_RECOUPED` when a settlement recoups less than the outstanding balance, and `ISSUED` or `PARTIALLY_RECOUPED` → `RECOUPED` when recoupment completes, at which point `recouped_cents` equals `amount_cents`; each recoupment recomputes `outstanding_cents` and reduces the grower's `advance_outstanding_cents` accordingly. Once the advance's pool is `SETTLED`, a `PoolAccountant` may write off the remaining balance, moving `ISSUED` or `PARTIALLY_RECOUPED` → the terminal `WRITTEN_OFF` — a write-off attempted before settlement fails with `ERR_POOL_NOT_ACCEPTING`. Writing off sets `written_off_cents` to the prior `outstanding_cents`, drops `outstanding_cents` to zero, and reduces the grower's `advance_outstanding_cents` by the written-off amount with a grower version bump. Advances can be listed with `grower_id`, `pool_id`, or `status` filters; a `Grower` caller sees only its own.

### 3.7. Caretaking Services and Grower Billing

Caretaking covers grove work — spraying, fertilizing, pruning, mowing — that the packinghouse performs and bills back. A `Grower` (for one of its own groves only) or a `FieldSupervisor` requests an order with `grove_id`, a `service_type` of `SPRAY`, `FERTILIZE`, `PRUNE`, or `MOW`, a `service_date` in YYYY-MM-DD form, `acres_treated` greater than zero and no more than the grove's `acreage` — an excess fails with `ERR_ACRES_EXCEED_GROVE` — and an optional `chemical_cost_cents` that defaults to zero and must remain zero unless the service is `SPRAY` (`ERR_CHEMICAL_COST_NOT_ALLOWED`). The grove must be enrolled in the program — `caretaking_enrolled` true, else `ERR_CARETAKING_NOT_ENROLLED` — and `PRODUCTIVE` (`ERR_GROVE_RETIRED`), and the grower must be `ACTIVE` (`ERR_GROWER_NOT_ACTIVE`). An order is born `REQUESTED` with `rate_tier`, `line_amount_cents`, and `invoice_id` unset. The orders collection can be filtered by `grove_id`, `invoice_id`, `status`, or `service_type`; a `Grower` caller sees only its own groves' orders.

A `FieldSupervisor` schedules a requested order (`REQUESTED` → `SCHEDULED`) and later completes it (`SCHEDULED` → `COMPLETED`). Completion is when money attaches: the system derives the order's `rate_tier` from the grove's `acreage` — `SMALL` below 40 acres, `MEDIUM` from 40 through 120 acres inclusive, `LARGE` above 120 — and computes `line_amount_cents` as two components, each rounded half-up to whole cents before they are summed, never re-rounded afterward. The labor component is `acres_treated` multiplied by the per-acre rate for the service and tier; the chemical component, present only for `SPRAY`, is `chemical_cost_cents` marked up by twelve percent. The per-acre rates in cents are: `SPRAY` 4200 on `SMALL`, 3900 on `MEDIUM`, 3500 on `LARGE`; `FERTILIZE` 3800, 3500, 3100; `PRUNE` 5500, 5200, 4800; and `MOW` 1800, 1700, 1500. Cancellation moves an order from `REQUESTED` or `SCHEDULED` to the terminal `CANCELLED`, performed by the owning `Grower`, a `FieldSupervisor`, or the system itself during grower termination (§3.1) or grove retirement (§3.1).

Billing runs through invoices drafted by a `PoolAccountant`. Drafting takes `grower_id`, `period_start`, and `period_end` — both inclusive dates in YYYY-MM-DD form, with the end no earlier than the start (`ERR_INVALID_REQUEST`) — and sweeps up every order of the grower's groves that is `COMPLETED`, not yet invoiced (`invoice_id` still null), and dated within the period; the swept order ids are recorded in `line_order_ids`, ordered by `service_date` ascending and then by `created_at` ascending, and `total_cents` is set to the sum of the member orders' `line_amount_cents`. An invoice is born `DRAFT` with `paid_cents` zero.

Issuing moves a draft `DRAFT` → `ISSUED`. Issuance requires the grower not to be `TERMINATED` (`ERR_GROWER_NOT_ACTIVE`) and the sweep to have captured at least one order (`ERR_INVALID_STATE_TRANSITION` on an empty `line_order_ids`). On issue, every swept order moves `COMPLETED` → the terminal `INVOICED` with its `invoice_id` set, and the grower's `caretaking_balance_cents` rises by `total_cents` with a grower version bump. A draft may instead be voided (`DRAFT` → `VOID`, terminal) with no financial effect.

Payments come from the owing `Grower` or a `PoolAccountant`, each carrying an `amount_cents`. The amount must be positive (`ERR_PAYMENT_AMOUNT_INVALID`, HTTP 400) and no more than the invoice's remaining balance — `total_cents` minus `paid_cents` — with an excess rejected as `ERR_INVOICE_OVERPAYMENT`. A payment smaller than the remaining balance moves `ISSUED` → `PARTIALLY_PAID`; one exactly equal to the remaining balance moves `ISSUED` → `PAID`, and a later such payment moves `PARTIALLY_PAID` → `PAID`, which is terminal. Each payment raises `paid_cents` by the amount and reduces the grower's `caretaking_balance_cents` by the same amount with a grower version bump.

Disputes belong to the grower: the owning `Grower` moves an `ISSUED` invoice to `DISPUTED`, which suspends the open amount — `total_cents` minus `paid_cents` — from the grower's `caretaking_balance_cents` while the dispute is open. A `PoolAccountant` then reissues, moving `DISPUTED` → `ISSUED` with an `adjusted_total_cents` that must be positive, no more than the original total, and at least the `paid_cents` already collected (`ERR_INVALID_REQUEST` otherwise); the invoice's `total_cents` becomes the adjusted figure and the grower's `caretaking_balance_cents` rises by the adjusted total minus `paid_cents`. The dispute-and-reissue loop may repeat. Invoices can be listed with `grower_id` or `status` filters; a `Grower` caller sees only its own.

### 3.8. Pest Quarantine and the Compliance Cascade

A `ComplianceOfficer` issues a quarantine order with a `scope_type` of `GROVE` or `COUNTY_ZONE`, a `pest_type` of `CANKER`, `HLB_GREENING`, `FRUIT_FLY`, or `BLACK_SPOT`, and the scope's target: a `GROVE`-scoped order requires `grove_id` and must leave `county_code` null, while a `COUNTY_ZONE`-scoped order requires `county_code` and must leave `grove_id` null — a malformed combination fails with `ERR_INVALID_REQUEST`. The order is born `ACTIVE`, stamped with `issued_at` from the logical clock and `issued_by` from the caller's `X-User-ID`.

Activation fires the quarantine cascade, atomically within the create request. Every covered grove — the named grove for `GROVE` scope, or every grove whose `county_code` matches for `COUNTY_ZONE` scope — has its `quarantine_posture` recomputed to `QUARANTINED`. Each covered grove's `SCHEDULED` harvest assignments are cancelled, releasing the crews' committed window capacity. Each covered grove's deliveries still `CLEAR` are held, moving to `HELD`. Every affected grove, assignment, and delivery has its `version` incremented and `updated_at` refreshed. While a grove's posture is `QUARANTINED`, the operations that require a clear posture — assignment creation and start, delivery receiving, export-lot creation, inspection requests, and certification — are refused with `ERR_GROVE_QUARANTINED` (HTTP 422), and its `HELD` deliveries refuse sorting and degreening-release work with `ERR_DELIVERY_REGULATORY_HOLD`.

Release is the second segregation-of-duties gate in compliance: a `ComplianceOfficer` releases an order (`ACTIVE` → `RELEASED`, terminal) only when the request's `inspection_passed` is true — anything else fails with `ERR_QUARANTINE_RELEASE_REQUIREMENTS` — and only when the releasing officer's `X-User-ID` differs from the order's `issued_by` (`ERR_SEGREGATION_OF_DUTIES`). The release stamps `released_at` and `released_by`, then recomputes the posture of every affected grove: a grove returns to `CLEAR` only when no other `ACTIVE` order still covers it, whether by grove scope or county scope. As each grove clears, every one of its deliveries sitting in `HELD` moves to `RELEASED`, provided no other hold cause remains, with the affected entities' versions incremented. Orders can be listed with `grove_id`, `county_code`, `status`, or `pest_type` filters.

### 3.9. Export Lots and Phytosanitary Certification

Export begins with a `ComplianceOfficer` building a lot: `destination_market` of `JAPAN`, `EU`, or `KOREA`; `variety`; a `grade` of `FANCY`, `CHOICE`, or `STANDARD`; `boxes` greater than zero; a `source_channel_id`; a `source_grove_id` naming the registered grove of origin for protocol declarations; and an optional `cold_treatment_hours` of zero or more, defaulting to 0. The source channel must be an `EXPORT` channel of matching variety and destination market whose week matches the fruit's pool week, or the create fails with `ERR_CHANNEL_MISMATCH`; the lot's `pool_id` is resolved from the source channel's variety and `week_start`. Building the lot reserves boxes from the channel's posted allocation: `boxes` may not exceed the channel's posted-allocation boxes not already reserved by other lots (`ERR_CHANNEL_CAPACITY_EXCEEDED`). The source grove's `quarantine_posture` must be `CLEAR` (`ERR_GROVE_QUARANTINED`). A lot is born `BUILDING`, with `inspection_requested_by`, `phyto_certificate_id`, and `diverted_to` all null. Lots can be listed with `destination_market`, `status`, `variety`, `source_grove_id`, `source_channel_id`, `pool_id`, or `phyto_certificate_id` filters.

Requesting inspection moves a lot `BUILDING` → `INSPECTION_READY`. Three protocol gates apply: for a `JAPAN`-bound lot, `cold_treatment_hours` must be at least 24 — a full day of cold treatment — failing which the request is rejected with `ERR_COLD_TREATMENT_INSUFFICIENT`; the source grove's posture must be `CLEAR` (`ERR_GROVE_QUARANTINED`); and for a `JAPAN`-bound lot, no `ACTIVE` `FRUIT_FLY` quarantine order may cover the source grove or its county, failing which the request is rejected with `ERR_FRUIT_FLY_PROTOCOL_BLOCK` — per §2.6, this fruit-fly check is evaluated before the generic posture gate. A successful request stamps `inspection_requested_by` with the caller's `X-User-ID`.

Certification records the official inspection against the lot — the path identifies it as `export_lot_id` — with a globally unique `certificate_number` and an `inspection_result` of `PASS` or `FAIL`. The issuing officer's `X-User-ID` must differ from the lot's `inspection_requested_by` (`ERR_SEGREGATION_OF_DUTIES`), and the lot must actually be `INSPECTION_READY` (`ERR_INVALID_STATE_TRANSITION`). On `PASS`, the source grove's posture is re-checked and must still be `CLEAR` (`ERR_GROVE_QUARANTINED`); the certificate is born `ISSUED`, stamped with `issued_at` from the logical clock and an `expires_at` exactly fourteen days later; and the lot moves `INSPECTION_READY` → `CERTIFIED` with its `phyto_certificate_id` set to the new certificate. On `FAIL`, the certificate record is created directly in `REVOKED` status as the failed-inspection record, and the lot moves to `REJECTED`. A rejected lot can be reworked — `REJECTED` → `BUILDING` — which clears `inspection_requested_by` and applies an optional `cold_treatment_hours` update, so the rework-and-reinspect loop may repeat. Certificates of a lot can be listed, and any certificate can be read by its `id`.

Shipping is the terminal success: a `CERTIFIED` lot ships only while its `phyto_certificate_id` references a certificate still in `ISSUED` status (`ERR_INVALID_STATE_TRANSITION` otherwise) and the logical clock reads strictly before the certificate's `expires_at` — a ship attempted at or after the expiry instant fails with `ERR_CERT_EXPIRED`. Shipping moves the lot `CERTIFIED` → `SHIPPED` and consumes the certificate, moving it `ISSUED` → `CONSUMED`.

Diversion sends a lot to the juice channel instead. It is available from `BUILDING`, from `INSPECTION_READY`, and from `CERTIFIED` — from any other state the attempt fails with `ERR_INVALID_STATE_TRANSITION` — and in all three cases requires the lot's pool to be `OPEN` or `INTAKE_CLOSED` (`ERR_POOL_NOT_ACCEPTING`) and a `JUICE` channel to exist for the lot's variety and pool week (`ERR_NO_JUICE_CHANNEL`). Diversion moves the lot to the terminal `DIVERTED` with `diverted_to` set to `JUICE`, and adjusts the pool's `posted_proceeds_cents` by the lot's `boxes` multiplied by the difference between the juice channel's `price_cents_per_box` and the source export channel's `price_cents_per_box` — a credit when juice pays more, a debit when it pays less; the pool's `posted_ge_boxes` is unchanged, since grade-equivalent boxes measure fruit rather than destination, and the pool's provisional price is recomputed with a version bump. Diverting from `CERTIFIED` additionally revokes the attached certificate, moving it `ISSUED` → `REVOKED`; diversions from `BUILDING` or `INSPECTION_READY` have no certificate to touch.

A certificate may also be revoked directly by a `ComplianceOfficer`, moving `ISSUED` → `REVOKED`, provided its lot is not `SHIPPED` (`ERR_INVALID_STATE_TRANSITION`); if the lot was `CERTIFIED`, it returns to `INSPECTION_READY` with its `phyto_certificate_id` cleared and must be re-inspected before it can ship. `CONSUMED` and `REVOKED` are terminal for a certificate.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource return `200 OK`. Recording a caretaking invoice payment creates a payment record and therefore returns `201 Created`, with the updated invoice as the payload; the logical-clock setter returns `200 OK`. The complete request and response semantics of each endpoint are defined by the workflows in §3 — this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/packinghouse/_clock/set_current_utc` | Set the server's logical clock | PackinghouseAdmin |
| POST | `/packinghouse/growers` | Onboard a grower | PackinghouseAdmin |
| GET | `/packinghouse/growers` | List growers | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| GET | `/packinghouse/growers/{id}` | Get one grower; Grower role may read only its own id | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer, Grower |
| POST | `/packinghouse/growers/{id}/suspend` | Suspend a grower (fiscal standing gate) | PoolAccountant |
| POST | `/packinghouse/growers/{id}/reinstate` | Reinstate a suspended grower | PoolAccountant |
| POST | `/packinghouse/growers/{id}/terminate` | Terminate a grower with zero outstanding advances and zero caretaking balance | PoolAccountant |
| POST | `/packinghouse/groves` | Register a grove under a grower | PackinghouseAdmin |
| GET | `/packinghouse/groves` | List groves; Grower role is scoped to its own groves | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer, Grower |
| GET | `/packinghouse/groves/{id}` | Get one grove | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer, Grower |
| POST | `/packinghouse/groves/{id}/retire` | Retire a grove | PackinghouseAdmin |
| POST | `/packinghouse/groves/{grove_id}/maturity-tests` | Record a maturity test for a grove; supersedes the grove's CURRENT test (OCC on grove.version) | QualityInspector |
| GET | `/packinghouse/groves/{id}/maturity-tests` | List maturity tests of a grove, newest first | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| GET | `/packinghouse/maturity-tests/{id}` | Get one maturity test | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| POST | `/packinghouse/crews` | Register a harvest crew | PackinghouseAdmin |
| GET | `/packinghouse/crews` | List crews | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| GET | `/packinghouse/crews/{id}` | Get one crew | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| POST | `/packinghouse/crews/{id}/deactivate` | Deactivate a crew with no open assignments | PackinghouseAdmin |
| POST | `/packinghouse/harvest-assignments` | Schedule a crew on a grove for a half-open window | FieldSupervisor |
| GET | `/packinghouse/harvest-assignments` | List assignments | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| GET | `/packinghouse/harvest-assignments/{id}` | Get one assignment | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| POST | `/packinghouse/harvest-assignments/{id}/start` | Start a scheduled assignment (maturity + quarantine + window gates) | FieldSupervisor |
| POST | `/packinghouse/harvest-assignments/{id}/complete` | Complete an in-progress assignment with actual boxes | FieldSupervisor |
| POST | `/packinghouse/harvest-assignments/{id}/cancel` | Cancel a scheduled (or unstarted in-progress) assignment | FieldSupervisor |
| POST | `/packinghouse/deliveries` | Receive a truckload of fruit at the packinghouse; resolves pool by variety + week of received_at | FieldSupervisor |
| GET | `/packinghouse/deliveries` | List deliveries | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| GET | `/packinghouse/deliveries/{id}` | Get one delivery | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| POST | `/packinghouse/deliveries/{id}/hold` | Place a regulatory hold on a delivery | ComplianceOfficer |
| POST | `/packinghouse/deliveries/{id}/release` | Release a held delivery | ComplianceOfficer |
| POST | `/packinghouse/deliveries/{id}/condemn` | Condemn a held delivery; auto-voids its OPEN/VERIFIED sort run | ComplianceOfficer |
| POST | `/packinghouse/deliveries/{id}/close` | Close a sorted delivery once its pool is priced | LineOperator |
| POST | `/packinghouse/degreening-rooms` | Register a degreening room | PackinghouseAdmin |
| GET | `/packinghouse/degreening-rooms` | List degreening rooms | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| GET | `/packinghouse/degreening-rooms/{id}` | Get one degreening room | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| POST | `/packinghouse/degreening-rooms/{id}/enter-maintenance` | Take a room out of service (requires no CONDITIONING sessions) | PackinghouseAdmin |
| POST | `/packinghouse/degreening-rooms/{id}/exit-maintenance` | Return a room to service | PackinghouseAdmin |
| POST | `/packinghouse/degreening-sessions` | Load delivery boxes into a degreening room (aggregate-capacity overlap check) | LineOperator |
| GET | `/packinghouse/degreening-sessions` | List degreening sessions | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| GET | `/packinghouse/degreening-sessions/{id}` | Get one degreening session | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| POST | `/packinghouse/degreening-sessions/{id}/release` | Release a conditioning session; duration bounds enforced unless QualityInspector overrides | LineOperator, QualityInspector |
| POST | `/packinghouse/degreening-sessions/{id}/abort` | Abort a conditioning session; boxes still count toward degreening completion | LineOperator |
| POST | `/packinghouse/sort-runs` | Create a sort run with measured grade outturn (OCC on delivery.version; one non-VOIDED run per delivery) | LineOperator |
| GET | `/packinghouse/sort-runs` | List sort runs | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| GET | `/packinghouse/sort-runs/{id}` | Get one sort run | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| POST | `/packinghouse/sort-runs/{id}/verify` | Quality verification of a sort run (verifier must differ from creator) | QualityInspector |
| POST | `/packinghouse/sort-runs/{id}/post` | Post a verified sort run: runs the packout allocation waterfall and accrues to the pool | LineOperator |
| POST | `/packinghouse/sort-runs/{id}/void` | Void an OPEN or VERIFIED sort run | LineOperator |
| POST | `/packinghouse/sort-runs/{id}/reverse` | Reverse a POSTED sort run while its pool is still open (compensating action) | PoolAccountant |
| POST | `/packinghouse/allocation-channels` | Configure a weekly marketing allocation channel | PackinghouseAdmin |
| GET | `/packinghouse/allocation-channels` | List allocation channels | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| GET | `/packinghouse/allocation-channels/{id}` | Get one allocation channel | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| POST | `/packinghouse/pools` | Open a variety pool for a week | PoolAccountant |
| GET | `/packinghouse/pools` | List pools | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer, Grower |
| GET | `/packinghouse/pools/{id}` | Get one pool | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer, Grower |
| POST | `/packinghouse/pools/{id}/close-intake` | Close pool intake (all pool deliveries must be sorted/closed or condemned) | PoolAccountant |
| POST | `/packinghouse/pools/{id}/set-price` | Set or re-set the final pool price (OCC on pool.version) | PoolAccountant |
| POST | `/packinghouse/pools/{id}/settle` | Settle the pool: per-grower settlement waterfall with advance recoupment | PoolAccountant |
| GET | `/packinghouse/pools/{id}/settlement-statements` | Per-grower settlement statements for a pool (share, offset, recoup, paid) | PackinghouseAdmin, PoolAccountant, Grower |
| POST | `/packinghouse/advances` | Request an advance against a pool; Grower may request only for itself | Grower, PoolAccountant |
| GET | `/packinghouse/advances` | List advances; Grower role is scoped to its own advances | PackinghouseAdmin, PoolAccountant, ComplianceOfficer, Grower |
| GET | `/packinghouse/advances/{id}` | Get one advance; Grower role only its own | PackinghouseAdmin, PoolAccountant, ComplianceOfficer, Grower |
| POST | `/packinghouse/advances/{id}/approve` | Approve an advance (cap check against projected pool value) | PoolAccountant |
| POST | `/packinghouse/advances/{id}/deny` | Deny a requested advance | PoolAccountant |
| POST | `/packinghouse/advances/{id}/write-off` | Write off the remaining outstanding balance of an advance whose pool is SETTLED | PoolAccountant |
| POST | `/packinghouse/caretaking-orders` | Request a caretaking service for an enrolled grove; Grower only for its own groves | Grower, FieldSupervisor |
| GET | `/packinghouse/caretaking-orders` | List caretaking orders; Grower role scoped to own groves | PackinghouseAdmin, PoolAccountant, FieldSupervisor, Grower |
| GET | `/packinghouse/caretaking-orders/{id}` | Get one caretaking order | PackinghouseAdmin, PoolAccountant, FieldSupervisor, Grower |
| POST | `/packinghouse/caretaking-orders/{id}/schedule` | Schedule a requested caretaking order | FieldSupervisor |
| POST | `/packinghouse/caretaking-orders/{id}/complete` | Complete a scheduled order; computes the line amount (rate tier x acres + chemical markup) | FieldSupervisor |
| POST | `/packinghouse/caretaking-orders/{id}/cancel` | Cancel a REQUESTED or SCHEDULED order; Grower only for its own groves | Grower, FieldSupervisor |
| POST | `/packinghouse/caretaking-invoices` | Draft an invoice sweeping the grower's COMPLETED uninvoiced orders in the period | PoolAccountant |
| GET | `/packinghouse/caretaking-invoices` | List caretaking invoices; Grower role scoped to own | PackinghouseAdmin, PoolAccountant, Grower |
| GET | `/packinghouse/caretaking-invoices/{id}` | Get one caretaking invoice | PackinghouseAdmin, PoolAccountant, Grower |
| POST | `/packinghouse/caretaking-invoices/{id}/issue` | Issue a draft invoice; marks orders INVOICED and debits the grower's caretaking balance | PoolAccountant |
| POST | `/packinghouse/caretaking-invoices/{id}/payments` | Record a payment against an issued invoice (partial allowed, overpayment rejected) | Grower, PoolAccountant |
| POST | `/packinghouse/caretaking-invoices/{id}/dispute` | Dispute an issued invoice (suspends the open amount from the grower balance) | Grower |
| POST | `/packinghouse/caretaking-invoices/{id}/reissue` | Reissue a disputed invoice at an adjusted total (revision loop back to ISSUED) | PoolAccountant |
| POST | `/packinghouse/caretaking-invoices/{id}/void` | Void a draft invoice | PoolAccountant |
| POST | `/packinghouse/quarantine-orders` | Issue a pest quarantine order on a grove or county zone; fires the quarantine cascade | ComplianceOfficer |
| GET | `/packinghouse/quarantine-orders` | List quarantine orders | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| GET | `/packinghouse/quarantine-orders/{id}` | Get one quarantine order | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| POST | `/packinghouse/quarantine-orders/{id}/release` | Release a quarantine order after a passed inspection (releasing officer must differ from issuer) | ComplianceOfficer |
| POST | `/packinghouse/export-lots` | Build an export lot drawing boxes from an EXPORT channel's posted allocation | ComplianceOfficer |
| GET | `/packinghouse/export-lots` | List export lots | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| GET | `/packinghouse/export-lots/{id}` | Get one export lot | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| POST | `/packinghouse/export-lots/{id}/request-inspection` | Move a BUILDING lot to INSPECTION_READY (cold-treatment, grove posture, fruit-fly protocol gates) | ComplianceOfficer |
| POST | `/packinghouse/export-lots/{id}/rework` | Rework a REJECTED lot back to BUILDING (optionally updating cold-treatment hours) | ComplianceOfficer |
| POST | `/packinghouse/export-lots/{id}/divert` | Divert a lot to the juice channel; adjusts pool proceeds and revokes any attached certificate | ComplianceOfficer |
| POST | `/packinghouse/export-lots/{id}/ship` | Ship a CERTIFIED lot; requires an unexpired ISSUED certificate | ComplianceOfficer |
| POST | `/packinghouse/export-lots/{export_lot_id}/phytosanitary-certificates` | Record an inspection and (on PASS) issue the phytosanitary certificate for a lot | ComplianceOfficer |
| GET | `/packinghouse/export-lots/{id}/phytosanitary-certificates` | List certificates of a lot | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| GET | `/packinghouse/phytosanitary-certificates/{id}` | Get one certificate | PackinghouseAdmin, PoolAccountant, FieldSupervisor, QualityInspector, LineOperator, ComplianceOfficer |
| POST | `/packinghouse/phytosanitary-certificates/{id}/revoke` | Revoke an ISSUED certificate; the lot must be re-inspected | ComplianceOfficer |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue is a lookup summary only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_GROWER_OWNERSHIP_MISMATCH` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_GROVE_QUARANTINED` | 422 |
| `ERR_GROVE_RETIRED` | 409 |
| `ERR_DELIVERY_REGULATORY_HOLD` | 422 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_FRUIT_FLY_PROTOCOL_BLOCK` | 422 |
| `ERR_COLD_TREATMENT_INSUFFICIENT` | 422 |
| `ERR_QUARANTINE_RELEASE_REQUIREMENTS` | 422 |
| `ERR_CERT_EXPIRED` | 422 |
| `ERR_MATURITY_TEST_REQUIRED` | 422 |
| `ERR_MATURITY_NOT_PASSING` | 422 |
| `ERR_MATURITY_TEST_EXPIRED` | 422 |
| `ERR_ASSIGNMENT_WINDOW_NOT_OPEN` | 422 |
| `ERR_CREW_WINDOW_OVERLAP` | 409 |
| `ERR_CREW_CAPACITY_EXCEEDED` | 422 |
| `ERR_CREW_NOT_ACTIVE` | 409 |
| `ERR_ROOM_CAPACITY_EXCEEDED` | 422 |
| `ERR_ROOM_NOT_AVAILABLE` | 409 |
| `ERR_DEGREENING_DURATION_OUT_OF_BOUNDS` | 422 |
| `ERR_DEGREENING_REQUIRED` | 422 |
| `ERR_SORT_BOX_MISMATCH` | 422 |
| `ERR_SORT_RUN_ALREADY_ACTIVE` | 409 |
| `ERR_DUPLICATE_ENTITY` | 409 |
| `ERR_CHANNEL_CAPACITY_EXCEEDED` | 422 |
| `ERR_ACRES_EXCEED_GROVE` | 422 |
| `ERR_CHEMICAL_COST_NOT_ALLOWED` | 422 |
| `ERR_POOL_NOT_ACCEPTING` | 409 |
| `ERR_POOL_HAS_OPEN_DELIVERIES` | 409 |
| `ERR_ADVANCE_CAP_EXCEEDED` | 422 |
| `ERR_GROWER_NOT_ACTIVE` | 409 |
| `ERR_INVOICE_OVERPAYMENT` | 422 |
| `ERR_PAYMENT_AMOUNT_INVALID` | 400 |
| `ERR_CHANNEL_MISMATCH` | 422 |
| `ERR_ASSIGNMENT_NOT_ACTIVE` | 409 |
| `ERR_NO_JUICE_CHANNEL` | 422 |
| `ERR_CARETAKING_NOT_ENROLLED` | 422 |
