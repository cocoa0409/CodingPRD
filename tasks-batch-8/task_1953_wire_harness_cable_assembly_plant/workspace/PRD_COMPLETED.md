# Wire Harness Assembly API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Wire Harness Assembly API, the operational backbone of a contract wire-harness and cable-assembly plant building to IPC/WHMA workmanship standards. The plant's business is unforgiving in two directions at once: customers audit serialized workmanship evidence (crimp pull tests, continuity and hipot results, operator certifications) before they accept product, and several customers consign their own connector inventory into the plant, which makes the plant financially liable for every consigned piece that is consumed, scrapped, or returned. The API exists to make both directions auditable — every serialized harness traces back to a pinned drawing revision, a qualified applicator and program, a certified operator, and a kit whose material came from a known stock source.

The system governs the full production arc: engineering releases harness drawings with their connector-and-wire bills of material; process engineering registers crimp applicators, schedules setup windows, and qualifies cut/strip/crimp machine programs through first-article pull testing; quality inspectors sample crimp pull force per lot and can quarantine tooling on a failing sample, which ripples through programs, build orders, and already-built serialized units; production planners release build orders into kitting; materials clerks pick kits from factory stock and customer-consigned lots under strict no-substitution rules and deliver them line-side; line operators record serialized builds; quality inspectors record electrical tests under segregation of duties; and engineering change notices disposition work-in-process when a drawing revises mid-production. A deterministic logical clock — never the wall clock — drives every timestamp, certification window, and expiry decision so that audits and test-driving are fully reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and invariants that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which that user acts. A request missing either header — a blank or whitespace-only header value counts as missing — or presenting a role outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes exactly eight roles:

- `HarnessEngineer` — owns harness drawings, BOM components, and engineering change notices.
- `ProcessEngineer` — owns crimp applicators, setup windows, and cut/strip/crimp machine programs.
- `QualityManager` — owns operators, operator certifications, and the logical clock.
- `QualityInspector` — the certified inspector who records crimp pull tests and electrical tests and who may scrap harness units.
- `ProductionPlanner` — owns build orders and release to kitting.
- `MaterialsClerk` — owns consigned lots and kitting for line-side delivery.
- `LineOperator` — builds serialized harnesses and completes rework.
- `ShippingClerk` — ships tested harnesses.

Role identity is defined as follows. When `X-User-Role` is `QualityInspector`, `X-User-ID` is the `id` of the acting `Operator`; ownership-style stamps on resources that reference an `Operator` (for example `operator_id` on a pull-test record or `test_operator_id` on an electrical test record) take their value from `X-User-ID`, and segregation-of-duties checks compare it against the relevant foreign-key field. The same rule applies when `X-User-Role` is `LineOperator`: `X-User-ID` is the `id` of the acting `Operator`, and it is stamped onto each built harness as `built_by_operator_id`. When `X-User-Role` is `HarnessEngineer`, `ProcessEngineer`, `QualityManager`, `ProductionPlanner`, `MaterialsClerk`, or `ShippingClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.

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

List endpoints paginate through two query parameters. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100 — out-of-range values are clamped to the nearest bound rather than rejected, while a non-integer `limit` or `offset` is rejected with `ERR_INVALID_REQUEST`. The `offset` parameter sets the number of items skipped; it defaults to 0, and a negative value is clamped to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order, with ties broken by creation order (the order in which the resources were inserted); the same tie-break applies wherever this document processes resources in `created_at` order. When several filter parameters are supplied on one list call, they all apply conjunctively. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity and Common Properties

Every primary resource carries a standard set of system-managed fields. The `id` is a server-minted UUID with no type prefix. The `created_at` and `updated_at` fields are ISO 8601 UTC timestamps rendered at whole-second precision with a `Z` suffix (for example `2026-08-01T00:00:00Z`); timestamps supplied at finer precision are truncated to whole seconds when stored. `updated_at` refreshes on any mutation of the resource. The `version` field is a system-managed integer that starts at 1 on creation and increments by one on every mutation of the resource, including mutations caused by automatic reconciliations and cascades, and it underpins the optimistic concurrency rules of §2.7; within a single request a resource's version increments at most once, even when a cascade touches that resource several times.

Two resources are append-only evidence records and break this pattern: a crimp pull-test record and an electrical test record each carry only `id` and `created_at` from the common set. Both `updated_at` and `version` are absent on these two resources, because a recorded test result is never modified after creation.

The resource graph is flat: resources reference one another by foreign-key fields (for example a payload containing a `drawing_id`), and no resource is owned under another resource's URL path. When a request references resources by identifier — whether in the path or in the body — each identifier must resolve to an existing resource; the first unresolvable identifier, validated left-to-right, yields `ERR_NOT_FOUND` (HTTP 404). Requests to an undeclared path, or to a declared path with an unsupported method, are likewise rejected with `ERR_NOT_FOUND` (HTTP 404).

### 2.5. The Logical Clock

All notions of "now" in this system read a server-side logical clock, never the wall clock — with one exception: the response-envelope `api_request_timestamp` of §2.2 is generated from the wall clock. At server startup, before any clock-setting call, the logical clock reads exactly `2026-08-01T00:00:00Z`. A `QualityManager` may advance the clock through an admin-only test-driving capability that accepts a `to_iso8601` timestamp and returns the resulting `current_utc`; the clock accepts any valid timestamp — setting it backward is permitted, there is no regression rejection — and the server never falls back to wall-clock time at any point.

Every timestamp the server stamps on its own — `released_at`, `superseded_at`, `qualified_at`, `tested_at`, `issued_at`, `delivered_at`, `suspect_marked_at`, `applied_at`, `revoked_at` — reads this clock. Every derived rule that speaks of "now" — most importantly the computed certification status of §3.3 — likewise evaluates against this clock.

### 2.6. Validation Pipeline and Error Precedence

When several checks could reject the same request, the server evaluates them in a fixed priority order and surfaces the first failure. The tiers, from first to last, are:

1. **Request well-formedness** — the body parses as JSON and is a JSON object (an empty body is treated as an empty object); declared input fields are present with correct types (a required string field that is blank or whitespace-only counts as missing); enum values fall in their declared sets; conditional requirements hold (`opens_count` is required when `test_type` is `CONTINUITY`; `hipot_voltage_v`, `dwell_seconds`, `measured_leakage_ua`, and `leakage_limit_ua` are required when `test_type` is `HIPOT`); and field constraints hold (`qty_per_harness` at least 1, `qty_ordered` at least 1, `qty_received` at least 1, `qty_issued` at least 1, `planned_end_at` strictly after `planned_start_at`, `expires_at` strictly after `issued_at`, `wire_gauge_awg` an integer between 12 and 26 inclusive, cost-per-piece fields and `material_budget_cents` at least 0, cut and strip lengths strictly greater than 0, `opens_count` at least 0). Violations yield `ERR_INVALID_REQUEST` (HTTP 400). Undeclared or read-only payload fields are ignored and are not an error.
2. **Authentication** — the `X-User-Role` and `X-User-ID` headers are present and the role is one of the eight declared roles; otherwise `ERR_UNAUTHENTICATED` (HTTP 401).
3. **Authorization** — the acting role is listed for the endpoint; otherwise `ERR_FORBIDDEN` (HTTP 403).
4. **Existence** — path identifiers and body foreign-key identifiers resolve to existing resources, validated left-to-right; otherwise `ERR_NOT_FOUND` (HTTP 404).
5. **Stale-version checks** — the optimistic-concurrency rules of §2.7; otherwise the rule's 412 error.
6. **State preconditions** — the target resource is in a status that permits the operation (drawing `DRAFT` for component add and release, drawing `RELEASED` for program/build-order/ECN creation, program `DRAFT` for edit, applicator tooling preconditions for pull tests, build order `OPEN` for edit and cancel, build order `IN_BUILD` for harness creation, unit testable or shippable, kit `PICKING` for issues, kit `STAGED` for delivery, ECN `OPEN` for apply and cancel, and so on). These reject with the operation's dedicated 409 error.
7. **Business safety** — operator certification gating, segregation of duties, hipot class minimums, and consigned supply-type compliance. On electrical test recording, this tier has a fixed internal order: the certification check runs first, then segregation of duties, then the hipot voltage floor.
8. **Business referential integrity** — the issued component belongs to the order's pinned drawing revision, the referenced lot is issuable, the lot's part number matches the BOM line's, and a lot-sample pull test references the program actually loaded on the applicator.
9. **Business constraints** — on-hand sufficiency, per-line over-issue, setup-window and certification-window overlap, duplicate find numbers, rework limits, a single open ECN per drawing, a changed target revision, and uniqueness of the remaining plant-unique codes (`drawing_number`, `applicator_code`, `badge_no`, `lot_code`, `order_code`, `program_code`, `ecn_code`) — a violation of one of those uniqueness rules rejects with `ERR_INVALID_REQUEST` (HTTP 400), not a dedicated error.
10. **Temporal rules** — a certification cannot be issued already expired.
11. **Fiscal rules** — the material budget cap.

The ordering matters operationally. For example, on certification issuance the window-overlap check (tier 9) is evaluated before the expiry-in-the-future check (tier 10), so a certification that violates both surfaces `ERR_CERT_WINDOW_OVERLAP`, not `ERR_CERT_EXPIRY_NOT_FUTURE`. Similarly, a build-order edit carrying a stale `expected_build_order_version` against an order that has also left `OPEN` surfaces the tier-5 stale-version rejection rather than the tier-6 state rejection.

### 2.7. Optimistic Concurrency Control

Two write endpoints participate in optimistic concurrency control, and both treat the version field as a non-optional input.

A `PATCH /plant/build-orders/{id}` request must carry `expected_build_order_version` holding the client's last observed `version` of the target build order. Editing `qty_ordered` or `material_budget_cents` while the order is `OPEN` is legitimate at any time; however, if `expected_build_order_version` no longer matches the build order's current `version` — because another write has advanced it since the client last read the order — the request is rejected with `ERR_STALE_BUILD_ORDER_VERSION` (HTTP 412), preventing the client from overwriting state it has not observed.

A `PATCH /plant/machine-programs/{id}` request must likewise carry `expected_machine_program_version` matching the target program's current `version`. Editing cut, strip, or tooling parameters while the program is `DRAFT` is legitimate at any time; a mismatch is rejected with `ERR_STALE_PROGRAM_VERSION` (HTTP 412).

No other endpoint accepts a version field; the optimistic-concurrency mechanism applies only to these two edits.

### 2.8. Units, Precision, and Rounding

All monetary amounts are integer cents — `unit_cost_cents`, `unit_liability_cents`, `replacement_cost_cents`, `material_budget_cents`, `material_spent_cents`, `standard_cost_cents`, `actual_cost_cents`, `scrap_recovery_credit_cents`, `book_liability_cents`, and `replacement_liability_cents` are all whole-cent integers, and every monetary computation rounds half-up to integer cents at the step the business rule specifies. Crimp pull forces are newtons carried to one decimal place; the computed minimum `min_pull_force_n` rounds half-up to one decimal place, while the measured force `measured_force_n` is recorded exactly as supplied and compared against the snapshot minimum without any rounding. The hipot leakage comparison is likewise performed exactly on the supplied microamp values, with no rounding. Quantities of pieces and serialized units are integers throughout. Certification-window and expiry comparisons are made at second precision against the logical clock.

### 2.9. Workmanship Classes, Certification Gating, and Segregation of Duties

Every drawing, and therefore every program, build order, and serialized harness derived from it, carries an IPC/WHMA workmanship class: `IPC_CLASS_1`, `IPC_CLASS_2`, or `IPC_CLASS_3`. The class is not cosmetic — it scales the minimum crimp pull force a program demands (§3.2), it floors the hipot test voltage an electrical test may apply (§3.7), and it defines which operators may witness quality evidence: an operator recording a pull test or an electrical test must hold a certification whose `workmanship_class` equals the class of the program's drawing (for pull tests) or of the build order (for electrical tests), with a computed status of `ACTIVE` at the logical-clock now. A missing, expired, or revoked certification rejects the recording with `ERR_OPERATOR_NOT_CERTIFIED` (HTTP 409).

The plant enforces segregation of duties on serialized product: the operator who built a harness may not be the operator who records its electrical test. A test recording whose acting inspector equals the unit's `built_by_operator_id` is rejected with `ERR_SOD_BUILDER_CANNOT_TEST` (HTTP 409).

## 3. Business Logic & Workflows

### 3.1. Drawings, BOM Components, and Release

A `HarnessEngineer` authors a harness drawing by supplying a `drawing_number` (unique across the plant), the owning `customer_code`, a `revision` letter such as "A", and the `workmanship_class` (`IPC_CLASS_1`, `IPC_CLASS_2`, or `IPC_CLASS_3`). A new drawing is born in `DRAFT` status, and both `released_at` and `superseded_at` remain null.

While the drawing is `DRAFT`, the engineer builds its bill of material one component at a time. Each component line carries the `drawing_id` it belongs to, a `find_number` (unique within that drawing — adding a second line with the same `find_number` on the same drawing is rejected with `ERR_DUPLICATE_FIND_NUMBER`), a `component_type` of `CONNECTOR`, `TERMINAL`, `WIRE`, `SEAL`, or `SLEEVE`, the manufacturer part number `mpn`, a `qty_per_harness` of at least 1, a `supply_type` declaring the line `FACTORY_STOCK` or `CUSTOMER_CONSIGNED`, and a `unit_cost_cents` of at least 0. Component lines may only be added to a `DRAFT` drawing; the attempt on a drawing in any other status is rejected with `ERR_DRAWING_NOT_DRAFT`.

Releasing a drawing moves it `DRAFT → RELEASED`, stamps `released_at` from the logical clock, and increments its `version`. Release is refused with `ERR_DRAWING_EMPTY_BOM` when the drawing has no component lines, and with `ERR_DRAWING_NOT_DRAFT` when the drawing is not in `DRAFT`. Only a `RELEASED` drawing may anchor downstream work: creating a machine program, a build order, or an engineering change notice against a drawing that is not `RELEASED` is rejected with `ERR_DRAWING_NOT_RELEASED`. A released drawing leaves `RELEASED` only by supersession through an applied engineering change notice (§3.8), which moves it to the terminal `SUPERSEDED` status and stamps `superseded_at`. The component catalogue is listable with an optional `drawing_id` filter.

### 3.2. Applicators, Setup Windows, and Machine Programs

A `ProcessEngineer` registers each crimp applicator with a unique `applicator_code` and the `compatible_terminal_mpn` the applicator is tooled for. A new applicator starts `AVAILABLE`, with `current_program_id` and `qualified_at` null.

Machine programs encode the cut/strip/crimp recipe. Creating one requires a unique `program_code`, the `drawing_id` of a `RELEASED` drawing, the `applicator_id` it will run on, a `wire_gauge_awg` integer between 12 and 26 inclusive, a `wire_type` insulation code, a `cut_length_mm` and a `strip_length_mm` each strictly greater than 0, the `terminal_mpn` the program crimps, and a `terminal_type` of `OPEN_BARREL` or `CLOSED_BARREL`. A program is born in `DRAFT`.

Creation also computes the program's minimum crimp pull force, `min_pull_force_n`. The computation starts from a base force looked up by wire gauge: 15.0 newtons for gauges 26, 25, and 24; 30.0 newtons for gauges 23, 22, 21, and 20; 50.0 newtons for gauges 19, 18, 17, and 16; and 80.0 newtons for gauges 15, 14, 13, and 12. The base is multiplied by a terminal derating — 1.0 for `OPEN_BARREL`, 0.9 for `CLOSED_BARREL` — and then by a workmanship-class multiplier taken from the program's linked drawing: 1.0 for `IPC_CLASS_1`, 1.0 for `IPC_CLASS_2`, and 1.1 for `IPC_CLASS_3`. The product is rounded half-up to one decimal place. The three factors interact non-linearly: the tier table reads the gauge, the derating reads the terminal type, and the multiplier reads the drawing's class.

While a program remains `DRAFT`, the process engineer may edit it — `wire_gauge_awg`, `wire_type`, `cut_length_mm`, `strip_length_mm`, `terminal_mpn`, `terminal_type`, and `applicator_id` are all editable, and a field that is absent from the payload or explicitly null is left unchanged — provided the request carries `expected_machine_program_version` per §2.7. Editing a program that is not `DRAFT` is rejected with `ERR_PROGRAM_NOT_DRAFT`. Every accepted edit recomputes `min_pull_force_n` from the same formula and increments the program's `version`. Programs are listable filtered by `drawing_id` or `applicator_id`; applicators are listable filtered by `status` or `current_program_id`.

To load a program onto an applicator, the process engineer opens a setup window naming the `applicator_id`, the `program_id`, the `setup_operator_id` performing the work, and a planned half-open interval from `planned_start_at` to `planned_end_at` (the end must be strictly after the start, or the request fails as `ERR_INVALID_REQUEST`). An applicator may enter setup from `AVAILABLE`, `QUALIFIED`, or `QUARANTINED`; opening the window moves it to `IN_SETUP`, points its `current_program_id` at the setup's program, and increments its `version`. Two guards protect the schedule: an applicator with another `OPEN` setup rejects the new window with `ERR_APPLICATOR_SETUP_ALREADY_OPEN`, and a planned window that overlaps any existing setup window on the same applicator rejects with `ERR_APPLICATOR_SETUP_OVERLAP`; the already-open guard is evaluated before the overlap guard. Overlap uses half-open interval semantics — the new window overlaps an existing one when the new start falls before the existing end and the existing start falls before the new end; windows that merely touch at an endpoint are allowed. Closing a setup requires the setup still be `OPEN` — a close attempted in any other status is rejected with `ERR_INVALID_REQUEST` — and accepts a `closed_at` timestamp, which must be at or after the window's `planned_start_at` — an earlier close is rejected as `ERR_INVALID_REQUEST`. A successful close marks the setup `CLOSED`, stores `closed_at`, and returns the applicator from `IN_SETUP` to `AVAILABLE`, incrementing the applicator's `version`. Setups are listable filtered by `applicator_id`, `program_id`, or `setup_operator_id`.

### 3.3. Operators and Certification Windows

The `QualityManager` maintains the operator roster: each operator is created with an `operator_name` and a unique `badge_no`. Certification to a workmanship class is issued per operator by supplying the `operator_id`, the `workmanship_class`, an inclusive window start `issued_at`, and a window end `expires_at` that must be strictly after `issued_at`.

Two further rules govern issuance, evaluated in the pipeline order of §2.6. First, the new window must not overlap any non-`REVOKED` certification already held by the same operator for the same class. Overlap uses closed-interval semantics — the new window overlaps an existing one when the new `issued_at` is on or before the existing `expires_at` and the existing `issued_at` is on or before the new `expires_at` — so windows that merely touch at an endpoint are rejected, and the rejection is `ERR_CERT_WINDOW_OVERLAP`. Second, `expires_at` must lie strictly in the future of the logical clock at issuance; an already-expired certification cannot be issued and is rejected with `ERR_CERT_EXPIRY_NOT_FUTURE`. Because the overlap check outranks the temporal check, a request violating both surfaces the overlap error.

A certification's `status` is never stored; it is computed on every read and on every gated operation. The status is `REVOKED` when `revoked_at` is set; otherwise `EXPIRED` once the logical clock reaches or passes `expires_at` (holding an `ACTIVE` certification strictly requires the clock to read earlier than `expires_at`); otherwise `ACTIVE`. Expiry is purely derived — the logical clock crossing `expires_at` mutates nothing. The `QualityManager` may revoke a certification while its `revoked_at` is still null; revocation stamps `revoked_at` from the logical clock and increments `version`, after which the computed status reads `REVOKED`. Revoking an already-revoked certification is rejected with `ERR_INVALID_REQUEST`. Certifications are listable filtered by `operator_id` or `workmanship_class`.

### 3.4. Crimp Pull Testing and the Quarantine Cascade

A `QualityInspector` records crimp pull tests against an applicator-and-program pair, supplying the `applicator_id`, the `program_id`, a `sample_kind` of `FIRST_ARTICLE` or `LOT_SAMPLE`, and the `measured_force_n` read off the pull tester. The recording operator's `operator_id` is stamped from `X-User-ID`, and `tested_at` is stamped from the logical clock. Before anything is recorded, the inspector must hold an `ACTIVE` certification for the workmanship class of the program's drawing; otherwise the recording is rejected with `ERR_OPERATOR_NOT_CERTIFIED`.

At record time the program's current `min_pull_force_n` is copied onto the record as `min_pull_force_n_snapshot`, so later program edits never rewrite history. The record's `result` is `PASS` when the measured force is at least the snapshot minimum, and `FAIL` otherwise.

A first-article test is the qualification gate for tooling. Recording a `FIRST_ARTICLE` sample requires the applicator to be `AVAILABLE` with its `current_program_id` equal to the tested program, at least one `CLOSED` setup to exist for that applicator-and-program pair, and the program's status to be `DRAFT` or `HELD`; any shortfall is rejected with `ERR_FIRST_ARTICLE_PREREQUISITE`. A failing first-article test changes nothing beyond the record. When a first-article test passes, the applicator moves `AVAILABLE → QUALIFIED` with `qualified_at` stamped from the clock, and the program qualifies with it: `DRAFT → QUALIFIED` for a first qualification, or `HELD → QUALIFIED` for a requalification after a quarantine — requalification additionally requiring that at least one `CLOSED` setup for the pair was created after the quarantine occurred (creation order, not the clock, decides "after", so a frozen logical clock cannot blur the comparison). A program's return from `HELD` to `QUALIFIED` releases the orders it froze: every build order sitting in `QC_HOLD` whose `held_by_program_id` is that program restores to its saved `qc_hold_return_status`, clearing both `qc_hold_return_status` and `held_by_program_id`, processed in order of the orders' `created_at` ascending. Units thrown into `SUSPECT` by the quarantine are deliberately not auto-restored — they clear only through passing retests or scrap.

A lot-sample test is the in-production tripwire. Recording a `LOT_SAMPLE` requires the applicator to be `QUALIFIED` (otherwise `ERR_APPLICATOR_NOT_QUALIFIED`) and the tested `program_id` to equal the applicator's `current_program_id` (otherwise `ERR_APPLICATOR_PROGRAM_MISMATCH`). A passing lot sample changes nothing beyond the record. A failing lot sample fires the deepest cascade in the system. The applicator moves `QUALIFIED → QUARANTINED`. Every `QUALIFIED` machine program on that applicator moves to `HELD`. Each build order whose pinned drawing is the held program's drawing and whose status is `KITTING`, `IN_BUILD`, or `TESTING` moves to `QC_HOLD`, saving its prior status in `qc_hold_return_status` and recording the culprit program in `held_by_program_id`. Finally, the suspect sweep marks collateral product: every harness unit whose build order belongs to that same drawing and entered `QC_HOLD` through this quarantine, whose status is `BUILT`, `REWORK`, or `TEST_PASS`, and whose `created_at` is at or after the quarantined applicator's `qualified_at`, moves to `SUSPECT` — `suspect_marked_at` stamped from the clock and both `continuity_pass` and `hipot_pass` reset to false. The sweep processes build orders in `created_at` ascending order, then units within each order in `created_at` ascending order. Units on orders of other drawings, and units already `SHIPPED` or `SCRAPPED`, are never selected. Pull-test records are listable filtered by `applicator_id`, `program_id`, or `operator_id`.

### 3.5. Build Orders: Creation, Editing, and Release to Kitting

A `ProductionPlanner` opens a build order against a `RELEASED` drawing by supplying a unique `order_code`, the `drawing_id`, a `qty_ordered` of at least 1, and optionally a `material_budget_cents` spend cap — when omitted, the order is uncapped. At creation the order pins the drawing's current revision into `drawing_revision_pinned` and copies the drawing's class into its own `workmanship_class`; neither ever changes afterward, no matter how the drawing later revises. The serial counter `next_unit_seq` starts at 1, the `use_as_is_flag` starts false, all quantity and cost counters start at zero, and the order is born `OPEN`.

While the order is `OPEN`, the planner may edit `qty_ordered` or `material_budget_cents` — an absent or null `qty_ordered` leaves it unchanged, while a null `material_budget_cents` removes the cap (the order becomes uncapped), and lowering the cap below the amount already spent is permitted since the cap is enforced only when recording new issues (§3.6) — provided the request carries `expected_build_order_version` per §2.7; a stale version rejects with `ERR_STALE_BUILD_ORDER_VERSION`, and an edit attempted on an order that is no longer `OPEN` rejects with `ERR_BUILD_ORDER_NOT_OPEN`. The planner may also cancel an `OPEN` order outright, moving it `OPEN → CANCELLED`; cancellation on an order in any other status likewise rejects with `ERR_BUILD_ORDER_NOT_OPEN`.

Releasing to kitting is allowed while the order is `OPEN`, `KITTING`, `IN_BUILD`, or `TESTING`, provided no kit of the order is currently `PICKING` or `STAGED`; a release attempted in any other status, or with a `PICKING`/`STAGED` kit outstanding, is rejected with `ERR_BUILD_ORDER_NOT_OPEN`. From `OPEN` a successful release moves the order `OPEN → KITTING`; from the other releasable statuses the order's status is unchanged. Release then demands that at least one machine program for the order's drawing is `QUALIFIED` (otherwise `ERR_NO_QUALIFIED_PROGRAM`) — the releasability check runs before the qualified-program check. A successful release creates the next kit for the order: its `kit_seq` is one greater than the count of the order's existing kits, its status is `PICKING`, its `issues` list is empty, and its `shortage_count` initializes to the total needed across the pinned BOM — for each BOM line, `qty_per_harness` multiplied by the order's `qty_ordered`, summed. The response carries the updated build order (not the new kit).

The order's derived counters reconcile on every event that touches their inputs — harness creation, scrap, kit issue, kit void-by-return, or engineering-change disposition. The `qty_built` counter is the count of the order's harness units in `BUILT`, `TEST_PASS`, `REWORK`, `SUSPECT`, or `SHIPPED`; `qty_scrapped` counts units in `SCRAPPED`. The sum `qty_built` plus `qty_scrapped` is conserved across a build followed by its compensating scrap — the unit moves buckets, the sum does not change — and is invariant under shipping; when that sum reaches `qty_ordered`, the order advances `IN_BUILD → TESTING`. Two cost variants roll up alongside. The `standard_cost_cents` is `qty_built` multiplied by the per-harness standard cost — the sum, over the pinned BOM lines, of `qty_per_harness` times `unit_cost_cents` — and serves as the quoting and variance baseline. The `actual_cost_cents` is the sum over all non-voided kit issues of the order of `qty_issued` times `unit_cost_snapshot_cents`, and equals `material_spent_cents`; the two variants diverge whenever consigned liability differs from standard cost or issues over- or under-ship against the BOM. The `scrap_recovery_credit_cents` accumulator starts at zero and grows per §3.7. Build orders are listable filtered by `drawing_id`, `status`, or `held_by_program_id`.

### 3.6. Kits, Consigned Lots, and Line-Side Delivery

Customer-consigned connectors arrive under the `MaterialsClerk`'s custody. Receiving a lot records a unique `lot_code`, the `owner_customer_code`, the connector's `mpn`, a `unit_liability_cents` book liability per piece owed back to the customer if the piece is lost or scrapped, a `replacement_cost_cents` current replacement cost per piece (both at least 0), and a `qty_received` of at least 1. At receipt, `qty_on_hand` equals `qty_received`, every other bucket reads zero, and the lot is `ACTIVE`.

A consigned lot tracks five quantity buckets, and their sum is a conserved invariant: `qty_on_hand` plus `qty_issued_open` plus `qty_consumed` plus `qty_scrapped` plus `qty_returned` always equals `qty_received`, across every forward-and-compensating action pair the plant performs. Issuing moves pieces from `qty_on_hand` into `qty_issued_open`. Line-side delivery of a kit moves its consigned pieces from `qty_issued_open` into `qty_consumed`. Returning a kit voids its issues and moves pieces from `qty_issued_open` back to `qty_on_hand`. Scrapping a built unit moves its consigned content from `qty_consumed` into `qty_scrapped`. Returning the lot to the customer adds all of `qty_on_hand` into `qty_returned` and zeroes `qty_on_hand`. Two liabilities derive from the scrapped bucket and recompute whenever `qty_scrapped` changes: `book_liability_cents` is `qty_scrapped` times `unit_liability_cents` (the settlement-at-book-value variant), and `replacement_liability_cents` is `qty_scrapped` times `replacement_cost_cents` (the settlement-at-replacement-cost variant); the two diverge whenever replacement cost differs from book. When reconciliation finds both `qty_on_hand` and `qty_issued_open` at zero — after a delivery or a scrap transfer — the lot auto-transitions `ACTIVE → DEPLETED`. A lot return to the customer, performed by the `MaterialsClerk`, moves `ACTIVE → RETURNED` after the bucket transfer described above; returning a lot in any other status is rejected with `ERR_INVALID_REQUEST`.

Kitting fills a `PICKING` kit one issue at a time. Recording an issue requires the kit to be `PICKING` (otherwise `ERR_KIT_NOT_PICKING`) and carries the `component_id` of a BOM line, the `qty_issued`, a `source` of `FACTORY_STOCK` or `CONSIGNED_LOT`, and — for consigned issues — the `consigned_lot_id`. Each issue appends a line object to the kit's `issues` list capturing the `component_id`, `qty_issued`, `source`, `consigned_lot_id` (null for factory issues), a `unit_cost_snapshot_cents`, the `issued_at` clock timestamp, and a `voided` flag that starts false. The cost snapshot is taken at issue time: for a consigned issue it is the lot's `unit_liability_cents`; for a factory issue it is the BOM component's `unit_cost_cents`.

Issue recording walks the validation pipeline of §2.6, and its business checks deserve explicit statement. Supply-type compliance forbids substitution: a BOM line declared `CUSTOMER_CONSIGNED` may only be issued with `source` `CONSIGNED_LOT`, and a `FACTORY_STOCK` line only with `source` `FACTORY_STOCK` — crossing the two rejects with `ERR_CONSIGNED_SUBSTITUTION_FORBIDDEN`. The issued component must belong to the order's pinned drawing revision (otherwise `ERR_COMPONENT_NOT_ON_DRAWING`). A referenced consigned lot must be `ACTIVE` (otherwise `ERR_CONSIGNED_LOT_NOT_ISSUABLE`), and the lot's `mpn` must equal the BOM line's `mpn` (otherwise `ERR_CONSIGNED_MPN_MISMATCH`). The `qty_issued` must not exceed the lot's `qty_on_hand` (otherwise `ERR_CONSIGNED_INSUFFICIENT_ON_HAND`). Cumulative non-voided issues against a BOM line within the kit must not exceed that line's needed quantity — `qty_per_harness` times `qty_ordered` (otherwise `ERR_KIT_LINE_OVER_ISSUE`). And when the order carries a budget, the issue is allowed only if `material_spent_cents` plus this issue's extended cost (`qty_issued` times `unit_cost_snapshot_cents`) stays at or below `material_budget_cents` — equality is permitted, and only a strictly-greater result rejects with `ERR_MATERIAL_BUDGET_EXCEEDED`.

A consigned issue immediately moves `qty_issued` pieces from the lot's `qty_on_hand` into `qty_issued_open`. Every accepted issue recomputes the kit's `shortage_count` — summed over the pinned BOM lines, the amount by which each line's needed quantity exceeds its non-voided issued quantity, with negative differences counting as zero — and refreshes the order's `material_spent_cents` and `actual_cost_cents`. When the shortage reaches zero and at least one non-voided issue exists, the kit moves `PICKING → STAGED` on its own. Recording an issue returns `201 Created` with the updated kit.

Delivering a kit, again a `MaterialsClerk` action, requires the kit be `STAGED` (otherwise `ERR_KIT_NOT_STAGED`). Delivery moves each non-voided consigned issue's pieces from the lot's `qty_issued_open` into `qty_consumed`, stamps `delivered_at` from the clock, runs the lot reconciliation that may auto-`DEPLETE` the lot, and — on the order's first delivery — moves the build order `KITTING → IN_BUILD`. Returning a kit is allowed from `PICKING` or `STAGED` — any other status rejects with `ERR_INVALID_REQUEST` — and moves the kit to `RETURNED`: every non-voided issue becomes voided, consigned pieces move from `qty_issued_open` back to `qty_on_hand`, the kit's `shortage_count` recomputes (to the full needed quantity, since every issue is void), and the order's `material_spent_cents` and `actual_cost_cents` recompute with voided issues excluded. Kits are listable filtered by `build_order_id` or `status`.

### 3.7. Serialized Harnesses: Build, Electrical Test, Rework, Scrap, and Ship

Once an order is `IN_BUILD`, a `LineOperator` records each finished harness. Recording a build requires no payload fields; the order must be `IN_BUILD` (otherwise `ERR_BUILD_ORDER_NOT_IN_BUILD`). The server mints the unit's `serial_number` as the order's `order_code`, a hyphen, and the current `next_unit_seq` zero-padded to four digits — serial numbers are never reused, even after the corresponding unit is scrapped, because `next_unit_seq` only advances. The unit's `built_by_operator_id` is stamped from the acting operator's `X-User-ID`, its `drawing_revision_built` is copied from the order's `drawing_revision_pinned`, both `continuity_pass` and `hipot_pass` start false, `rework_count` starts at zero, and the unit is born `BUILT`. Each build recomputes the order counters, and when `qty_built` plus `qty_scrapped` reaches `qty_ordered` the order advances `IN_BUILD → TESTING`. Harness units are listable filtered by `build_order_id`, `built_by_operator_id`, or `status`.

Electrical testing is recorded per serialized unit by a `QualityInspector`, supplying the `harness_unit_id` and a `test_type` of `CONTINUITY` or `HIPOT`. A continuity record carries `opens_count`; a hipot record carries `hipot_voltage_v`, `dwell_seconds`, `measured_leakage_ua`, and `leakage_limit_ua` — the conditional requirements of §2.6 apply. The unit must be `BUILT`, `REWORK`, or `SUSPECT`; testing a unit in any other status rejects with `ERR_HARNESS_NOT_TESTABLE`. The recording inspector is stamped as `test_operator_id` from `X-User-ID`, and `tested_at` comes from the logical clock. Three safety gates then run in this fixed order. First, the inspector must hold an `ACTIVE` certification for the build order's workmanship class, else `ERR_OPERATOR_NOT_CERTIFIED`. Second, segregation of duties: the `test_operator_id` must differ from the unit's `built_by_operator_id`, else `ERR_SOD_BUILDER_CANNOT_TEST`. Third, for hipot tests only, the applied `hipot_voltage_v` must meet the class floor — 500 volts for `IPC_CLASS_1`, 1000 volts for `IPC_CLASS_2`, 1500 volts for `IPC_CLASS_3` — and a voltage below the floor rejects with `ERR_HIPOT_VOLTAGE_BELOW_CLASS_MIN` before any result is recorded.

The record's `result` derives from the measurement: a continuity test passes when `opens_count` is zero and fails otherwise; a hipot test passes when `measured_leakage_ua` is at most `leakage_limit_ua` — the boundary is inclusive — and fails otherwise. A passing record sets the corresponding flag on the unit (`continuity_pass` or `hipot_pass`) to true. When both flags stand true, the unit advances: from `BUILT` it moves to `TEST_PASS`; from `SUSPECT` it returns to `TEST_PASS` only when both a passing continuity record and a passing hipot record carry `tested_at` at or after the unit's `suspect_marked_at`, and the return clears `suspect_marked_at`. Every transition into `TEST_PASS` runs the order's completion bubble-up: when every unit of a `TESTING` order sits in `TEST_PASS`, `SHIPPED`, or `SCRAPPED` and `qty_built` is at least 1, the order completes `TESTING → COMPLETED`. A failing record drives the unit from `BUILT`, `REWORK`, or `SUSPECT` into `REWORK`, resets the failed test type's flag to false, and clears `suspect_marked_at` if it was set.

Rework is bounded. A `LineOperator` completes a rework cycle on a unit in `REWORK` — a unit in any other status rejects with `ERR_INVALID_REQUEST` — returning it to `BUILT` with `rework_count` incremented by one and both test flags reset to false; completing rework when `rework_count` has already reached 2 is rejected with `ERR_REWORK_LIMIT_EXCEEDED`. Shipping is the happy-path exit: a `ShippingClerk` ships a unit in `TEST_PASS`, moving it to the terminal `SHIPPED`; shipping a unit in any other status rejects with `ERR_UNIT_NOT_SHIPPABLE`.

Scrapping is the quality exit. A `QualityInspector` scraps a unit in `BUILT`, `REWORK`, or `SUSPECT`, supplying a `reason` of `DAMAGE` or `QC_SUSPECT`; scrapping a unit in any other status rejects with `ERR_INVALID_REQUEST`. The unit moves to the terminal `SCRAPPED` with `scrap_reason` set and `suspect_marked_at` cleared. Three side effects follow. First, scrap recovery credit: for each BOM line of the unit's pinned drawing revision — all supply types included — a line credit of `qty_per_harness` times `unit_cost_cents` times the 0.8 recovery rate is rounded half-up to integer cents, and the per-line credits are then summed into a unit credit (the rounding order is pinned: round each line first, then sum; summing first and rounding once is a different, rejected result). The unit credit accumulates into the order's `scrap_recovery_credit_cents`. Second, consigned transfer: the scrapped unit's consigned content moves each lot's `qty_consumed` into `qty_scrapped`, walking the unit's issues in first-in-first-out order by `issued_at` ascending with ties broken by `kit_seq` ascending (further ties break by issue recording order), and each affected lot's book and replacement liabilities recompute. Third, the order's `qty_built`, `qty_scrapped`, and `standard_cost_cents` recompute, and the order-level checks run: `IN_BUILD → TESTING` when the sum reaches `qty_ordered`, `TESTING → CANCELLED` when `qty_built` has fallen to zero (every built unit scrapped), and the completion check above. Electrical test records are listable filtered by `harness_unit_id` or `test_operator_id`.

### 3.8. Engineering Change Notices and WIP Disposition

When a drawing must revise, a `HarnessEngineer` opens an engineering change notice against a `RELEASED` drawing, supplying a unique `ecn_code`, the `drawing_id`, the `to_revision` letter, and a `wip_disposition` of `REWORK`, `USE_AS_IS`, or `SCRAP` declaring what happens to work-in-process at the old revision. The ECN snapshots the drawing's current revision into `from_revision` at creation. The `to_revision` must differ from `from_revision` — an unchanged revision rejects with `ERR_ECN_REVISION_UNCHANGED` — and at most one ECN may be `OPEN` per drawing: opening a second rejects with `ERR_ECN_ALREADY_OPEN`. The notice is born `OPEN`, with `applied_at` and `new_drawing_id` null.

Applying an ECN requires it be `OPEN` (otherwise `ERR_ECN_NOT_OPEN`) and fires a four-deep cascade. The old drawing moves `RELEASED → SUPERSEDED` with `superseded_at` stamped. A new harness drawing is created at the `to_revision` — its `drawing_number`, `customer_code`, and `workmanship_class` copied from the old drawing, its status `DRAFT`, and every component row of the old drawing copied onto it — and the ECN's `new_drawing_id` points at it. Then every build order pinned to the old drawing whose status is `OPEN`, `KITTING`, `IN_BUILD`, `TESTING`, or `QC_HOLD` is dispositioned in `created_at` ascending order, according to the `wip_disposition`. Under `USE_AS_IS`, the order's `use_as_is_flag` sets to true and nothing else moves. Under `REWORK`, each of the order's units in `BUILT` or `TEST_PASS` moves to `REWORK` with both test flags reset to false (its `rework_count` is not incremented). Under `SCRAP`, the order moves to `CANCELLED` (clearing `held_by_program_id` and `qc_hold_return_status` when set); every unit in `BUILT`, `REWORK`, `TEST_PASS`, or `SUSPECT` moves to `SCRAPPED` with `scrap_reason` `ECN_DISPOSITION`, earning the same per-unit scrap recovery credit and driving the same consigned consumed-to-scrapped FIFO transfer and liability recompute as a manual scrap; and every kit of the order in `PICKING` or `STAGED` moves to `RETURNED` with all its non-voided issues voided and consigned `qty_issued_open` restored to `qty_on_hand`. The ECN itself stamps `applied_at`, moves to the terminal `APPLIED`, and increments its `version`. Cancelling an ECN — also requiring `OPEN`, else `ERR_ECN_NOT_OPEN` — simply moves it to the terminal `CANCELLED` with no further effect. ECNs are listable filtered by `drawing_id`, `new_drawing_id`, or `status`.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource — including state transitions such as release, close, deliver, return, apply, ship, and scrap — return `200 OK`. All resources are mounted under the `/plant` prefix. Request payloads, side effects, and preconditions are defined by the narratives of §2 and §3; this table is an index, not a specification.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/plant/drawings` | Create a harness drawing revision in `DRAFT` | HarnessEngineer |
| GET | `/plant/drawings/{id}` | Get one drawing | Any authenticated role |
| POST | `/plant/drawings/{id}/release` | Release a drawing (`DRAFT → RELEASED`); requires a non-empty BOM | HarnessEngineer |
| POST | `/plant/components` | Add a BOM component to a `DRAFT` drawing | HarnessEngineer |
| GET | `/plant/components/{id}` | Get one component | Any authenticated role |
| GET | `/plant/components` | List components, filterable by `drawing_id` | Any authenticated role |
| POST | `/plant/consigned-lots` | Receive a customer-consigned connector lot | MaterialsClerk |
| GET | `/plant/consigned-lots/{id}` | Get one consigned lot | Any authenticated role |
| POST | `/plant/consigned-lots/{id}/return` | Return all remaining on-hand pieces to the customer (`ACTIVE → RETURNED`) | MaterialsClerk |
| POST | `/plant/operators` | Create an operator | QualityManager |
| GET | `/plant/operators/{id}` | Get one operator | Any authenticated role |
| POST | `/plant/operator-certifications` | Issue a workmanship-class certification; closed-interval overlap on (operator, class) rejected | QualityManager |
| GET | `/plant/operator-certifications/{id}` | Get one certification | Any authenticated role |
| GET | `/plant/operator-certifications` | List certifications, filterable by `operator_id` and `workmanship_class` | Any authenticated role |
| POST | `/plant/operator-certifications/{id}/revoke` | Revoke a certification (sets `revoked_at`; computed status `REVOKED`) | QualityManager |
| POST | `/plant/applicators` | Register a crimp applicator | ProcessEngineer |
| GET | `/plant/applicators/{id}` | Get one applicator | Any authenticated role |
| GET | `/plant/applicators` | List applicators, filterable by `current_program_id` and `status` | Any authenticated role |
| POST | `/plant/applicator-setups` | Open a planned setup window; applicator moves to `IN_SETUP`; half-open overlap check | ProcessEngineer |
| GET | `/plant/applicator-setups/{id}` | Get one setup | Any authenticated role |
| GET | `/plant/applicator-setups` | List setups, filterable by `applicator_id`, `program_id`, and `setup_operator_id` | Any authenticated role |
| POST | `/plant/applicator-setups/{id}/close` | Close an `OPEN` setup; applicator returns to `AVAILABLE` | ProcessEngineer |
| POST | `/plant/machine-programs` | Create a cut/strip/crimp program in `DRAFT` against a `RELEASED` drawing; computes `min_pull_force_n` | ProcessEngineer |
| GET | `/plant/machine-programs/{id}` | Get one machine program | Any authenticated role |
| GET | `/plant/machine-programs` | List machine programs, filterable by `drawing_id` and `applicator_id` | Any authenticated role |
| PATCH | `/plant/machine-programs/{id}` | Edit a `DRAFT` program (OCC via `expected_machine_program_version`) | ProcessEngineer |
| POST | `/plant/crimp-pull-tests` | Record a first-article or lot-sample pull test; recording operator stamped from `X-User-ID` | QualityInspector |
| GET | `/plant/crimp-pull-tests/{id}` | Get one pull-test record | Any authenticated role |
| GET | `/plant/crimp-pull-tests` | List pull-test records, filterable by `applicator_id`, `program_id`, and `operator_id` | Any authenticated role |
| POST | `/plant/build-orders` | Create a build order in `OPEN` against a `RELEASED` drawing; pins revision and class | ProductionPlanner |
| GET | `/plant/build-orders/{id}` | Get one build order | Any authenticated role |
| GET | `/plant/build-orders` | List build orders, filterable by `drawing_id`, `status`, and `held_by_program_id` | Any authenticated role |
| PATCH | `/plant/build-orders/{id}` | Edit `qty_ordered` / `material_budget_cents` while `OPEN` (OCC via `expected_build_order_version`) | ProductionPlanner |
| POST | `/plant/build-orders/{id}/release-to-kitting` | Create the next kit in `PICKING` (allowed from `OPEN`/`KITTING`/`IN_BUILD`/`TESTING` when no kit is `PICKING`/`STAGED`; moves `OPEN → KITTING`); returns the updated build order | ProductionPlanner |
| POST | `/plant/build-orders/{id}/cancel` | Move `OPEN → CANCELLED` | ProductionPlanner |
| POST | `/plant/build-orders/{id}/harness-units` | Record one built serialized harness; serial minted from `next_unit_seq` | LineOperator |
| GET | `/plant/harness-units/{id}` | Get one harness unit | Any authenticated role |
| GET | `/plant/harness-units` | List harness units, filterable by `build_order_id`, `built_by_operator_id`, and `status` | Any authenticated role |
| POST | `/plant/harness-units/{id}/complete-rework` | Move `REWORK → BUILT`; `rework_count` incremented; cap 2 | LineOperator |
| POST | `/plant/harness-units/{id}/scrap` | Scrap a unit in `BUILT`, `REWORK`, or `SUSPECT`; computes scrap credit and consigned transfer | QualityInspector |
| POST | `/plant/harness-units/{id}/ship` | Move `TEST_PASS → SHIPPED` | ShippingClerk |
| GET | `/plant/kits/{id}` | Get one kit | Any authenticated role |
| GET | `/plant/kits` | List kits, filterable by `build_order_id` and `status` | Any authenticated role |
| POST | `/plant/kits/{id}/issues` | Issue one BOM line into a `PICKING` kit; auto-stages at zero shortage | MaterialsClerk |
| POST | `/plant/kits/{id}/deliver` | Move `STAGED → DELIVERED_LINESIDE`; consigned issued-open moves to consumed | MaterialsClerk |
| POST | `/plant/kits/{id}/return` | Move `PICKING`/`STAGED → RETURNED`; voids all issues and restores consigned on-hand | MaterialsClerk |
| POST | `/plant/electrical-test-records` | Record a continuity or hipot test on a serialized harness; segregation of duties enforced | QualityInspector |
| GET | `/plant/electrical-test-records/{id}` | Get one electrical test record | Any authenticated role |
| GET | `/plant/electrical-test-records` | List electrical test records, filterable by `harness_unit_id` and `test_operator_id` | Any authenticated role |
| POST | `/plant/ecns` | Open an ECN against a `RELEASED` drawing; `from_revision` copied | HarnessEngineer |
| GET | `/plant/ecns/{id}` | Get one ECN | Any authenticated role |
| GET | `/plant/ecns` | List ECNs, filterable by `drawing_id`, `new_drawing_id`, and `status` | Any authenticated role |
| POST | `/plant/ecns/{id}/apply` | Apply an ECN: supersedes the drawing, creates the new `DRAFT` revision with copied BOM, dispositions WIP | HarnessEngineer |
| POST | `/plant/ecns/{id}/cancel` | Move `OPEN → CANCELLED` | HarnessEngineer |
| POST | `/plant/_clock/set_current_utc` | Set the logical clock; startup default is exactly `2026-08-01T00:00:00Z` | QualityManager |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The trigger condition for each error is defined where the rule lives, in §2 and §3.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_BUILD_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_STALE_PROGRAM_VERSION` | 412 Precondition Failed |
| `ERR_DRAWING_NOT_DRAFT` | 409 Conflict |
| `ERR_DRAWING_EMPTY_BOM` | 409 Conflict |
| `ERR_DRAWING_NOT_RELEASED` | 409 Conflict |
| `ERR_PROGRAM_NOT_DRAFT` | 409 Conflict |
| `ERR_APPLICATOR_SETUP_ALREADY_OPEN` | 409 Conflict |
| `ERR_FIRST_ARTICLE_PREREQUISITE` | 409 Conflict |
| `ERR_APPLICATOR_NOT_QUALIFIED` | 409 Conflict |
| `ERR_NO_QUALIFIED_PROGRAM` | 409 Conflict |
| `ERR_BUILD_ORDER_NOT_OPEN` | 409 Conflict |
| `ERR_BUILD_ORDER_NOT_IN_BUILD` | 409 Conflict |
| `ERR_HARNESS_NOT_TESTABLE` | 409 Conflict |
| `ERR_UNIT_NOT_SHIPPABLE` | 409 Conflict |
| `ERR_KIT_NOT_PICKING` | 409 Conflict |
| `ERR_KIT_NOT_STAGED` | 409 Conflict |
| `ERR_ECN_NOT_OPEN` | 409 Conflict |
| `ERR_OPERATOR_NOT_CERTIFIED` | 409 Conflict |
| `ERR_SOD_BUILDER_CANNOT_TEST` | 409 Conflict |
| `ERR_HIPOT_VOLTAGE_BELOW_CLASS_MIN` | 422 Unprocessable Entity |
| `ERR_CONSIGNED_SUBSTITUTION_FORBIDDEN` | 409 Conflict |
| `ERR_COMPONENT_NOT_ON_DRAWING` | 409 Conflict |
| `ERR_CONSIGNED_LOT_NOT_ISSUABLE` | 409 Conflict |
| `ERR_CONSIGNED_MPN_MISMATCH` | 422 Unprocessable Entity |
| `ERR_APPLICATOR_PROGRAM_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CONSIGNED_INSUFFICIENT_ON_HAND` | 409 Conflict |
| `ERR_KIT_LINE_OVER_ISSUE` | 409 Conflict |
| `ERR_APPLICATOR_SETUP_OVERLAP` | 409 Conflict |
| `ERR_CERT_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_FIND_NUMBER` | 409 Conflict |
| `ERR_REWORK_LIMIT_EXCEEDED` | 409 Conflict |
| `ERR_ECN_ALREADY_OPEN` | 409 Conflict |
| `ERR_ECN_REVISION_UNCHANGED` | 422 Unprocessable Entity |
| `ERR_CERT_EXPIRY_NOT_FUTURE` | 422 Unprocessable Entity |
| `ERR_MATERIAL_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
