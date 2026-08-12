# Railcar Repair Shop & AAR Billing API — Product Requirements Document

## 1. Introduction

An AAR-certified railcar repair shop lives at the intersection of mechanical work and railroad accounting. Cars arrive from a handling railroad carrying defects coded against the Association of American Railroads defect taxonomy; some of those defects are the car owner's financial responsibility, some belong to the delivering railroad, and a few are shared by rule. The shop must estimate every repair against a dated price master, obtain authorization from the financially responsible party before turning a wrench, and then — weeks later — reconcile a provisional estimate against a final Billing Repair Card whose numbers are computed from actual labor and actual parts, possibly under a different price window and a different labor rate than the estimate used. Disputes are not an edge case in this domain: counter-billing is a first-class, cyclical negotiation with hard ceilings, and warranty rework re-opens settled money long after a car has departed.

This document specifies the API for operating such a shop end to end: inbound car registration and inspection, AAR defect coding, work-order estimation and rule-based responsibility assignment, authorization under optimistic concurrency, shop-slot scheduling and mobile dispatch, quality-gated completion, dwell charging, Billing Repair Card submission, counter-bill negotiation, and warranty claims. The system keeps two ledgers — one per car owner and one per handling line — and guarantees that provisional and final money are computed by pinned, deterministic rules so that a dispute always reconciles against a number both parties can reproduce.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contract formats, and cross-cutting principles that apply to every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the caller's operational capacity. A request missing either header, carrying a malformed header, or naming an undeclared role is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400). The declared roles are `ShopAdmin`, `YardClerk`, `CarInspector`, `RepairForeman`, `QualityInspector`, `PartsClerk`, `BillingClerk`, `CarOwnerRep`, and `HandlingLineRep`. A valid caller attempting an operation outside their role's permissions is rejected with `ERR_FORBIDDEN_FOR_ROLE` (403). Read endpoints are open to the wildcard role `Any`: any request bearing a valid declared role and user id may read.

Two roles are entity-backed. When `X-User-Role` is `CarOwnerRep`, `X-User-ID` is the `id` of the acting CarOwner; ownership checks on any resource that references a CarOwner compare the resource's foreign-key field to `X-User-ID` — concretely, party-gated operations require `X-User-ID` to equal the railcar's `owner_id`. When `X-User-Role` is `HandlingLineRep`, `X-User-ID` is the `id` of the acting HandlingLine, and party-gated operations compare it against the railcar's `handling_line_id`. When `X-User-Role` is `ShopAdmin`, `YardClerk`, `CarInspector`, `RepairForeman`, `QualityInspector`, `PartsClerk`, or `BillingClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it for audit (for example as `inspector_user_id` on an Inspection, `created_by_user_id` on a WorkOrder, or `filed_by_id` on a CounterBill) but never compares it to any entity's `id`. The single place where two opaque identifiers are compared to each other is the quality gate's segregation-of-duties rule described in §2.12 and §3.5.

Beyond role permission, party-scoped operations enforce a responsibility match: authorizing or rejecting an estimate, accepting a Billing Repair Card, and filing a counter-bill or a warranty claim all require the acting entity-backed party to match the resource's determined responsible party. When the work order's `responsible_party` is `OWNER` or `SHARED`, the caller must be a `CarOwnerRep` whose `X-User-ID` equals the car's `owner_id`; when it is `HANDLING_LINE`, the caller must be a `HandlingLineRep` whose `X-User-ID` equals the car's `handling_line_id`. Withdrawing or revising a counter-bill and appealing a warranty claim are filer-only operations requiring `X-User-ID` to equal the record's `filed_by_id`. Any failure of these checks is rejected with `ERR_RESPONSIBILITY_MISMATCH` (403).

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

List endpoints paginate through two query parameters. `limit` sets the maximum number of items returned: it defaults to 10, with a minimum of 1 and a maximum of 100. `offset` sets the number of items skipped and defaults to 0. Unless otherwise specified, every list endpoint returns resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. The Logical Clock and Scheduled System Behavior

All time inside the system is read from a single logical clock — never from wall-clock time. At startup the logical clock reads exactly `2026-05-01T00:00:00Z`, and before any clock-setting call it continues to read exactly that instant. A `ShopAdmin` may advance the clock through a test-driving capability that accepts a target instant in `to_iso8601` and echoes the new reading as `current_utc`; every subsequent system timestamp — `arrived_at`, `completed_at`, `authorized_at`, `qa_review_entered_at`, `submitted_at`, `filed_at`, `departed_at`, and every `created_at`/`updated_at` — is taken from this clock.

Two time-driven transitions are not triggered by any user action on the affected resource; instead a `ShopAdmin` invokes a sweep capability on the shop. The sweep applies counter-bill expiry first — any counter-bill still `OPEN` or `REBUTTED` once the logical clock has passed the disputed card's dispute window plus an additional grace of the shop's `counter_window_days` moves to `EXPIRED` — and then applies deemed acceptance: any Billing Repair Card still `SUBMITTED` whose dispute window has passed with no `OPEN` or `REBUTTED` counter-bill moves to `ACCEPTED`, posting party balances exactly as a manual acceptance would. When the last active counter on a disputed card expires, the card returns from `DISPUTED` to `SUBMITTED` and is then eligible for deemed acceptance within the same sweep.

Durations measured in hours are expressed as fractional hours at two decimal places unless a rule states otherwise; wheelset measurements are millimeters at three decimal places; the responsibility decision's time comparison uses hours at three decimal places.

### 2.5. Shop Capacity Posture and Intake Gating

Each shop's booking pressure is derived per calendar day from its slot calendar. For the current logical-clock calendar day, the system sums, over every ShopSlot of the shop in `RESERVED` or `OCCUPIED` status whose half-open window intersects that day, the hours of overlap between the slot window and the day; this is the booked hours. The shop's capacity hours are its `stalls` multiplied by `stall_daily_hours` (eight bookable hours per stall per day by default). The shop's computed `current_posture` is `FULL` when booked hours are greater than or equal to capacity hours — a booked total exactly equal to capacity is `FULL` — otherwise `CONSTRAINED` when booked hours reach at least 85 percent of capacity, and otherwise `OPEN`. The posture is recomputed on every shop read and is exposed on the Shop resource as `current_posture`.

Posture is enforced at intake: creating a new work order on a day whose posture is `FULL` is rejected with `ERR_SHOP_AT_CAPACITY` (409). `CONSTRAINED` is advisory only and does not block intake.

### 2.6. The AAR Price Master: Effective Dating and Dual Rates

The price master prices each AAR `job_code` within a shop through dated entries. Every entry carries a `description`, a shop `labor_rate_cents_per_hour`, a `mobile_labor_rate_cents_per_hour` used when work is routed to a mobile crew, the AAR `standard_labor_hours` used for estimates, a flat `mobile_trip_surcharge_cents` applied once per mobile work order, a `mobile_eligible` flag governing whether the job may be routed `MOBILE`, and a `shared_split` flag (defaulting to false) that forces 50/50 responsibility sharing regardless of wear-group rules. Entries are effective over a closed date interval from `effective_from` through `effective_to`, inclusive on both ends.

For a given shop and `job_code`, the closed effective windows of two entries must never overlap; creating an entry whose window overlaps an existing entry for the same shop and job code is rejected with `ERR_PRICE_WINDOW_OVERLAP` (409). Because windows never overlap, resolving an entry for a job code at a given date yields at most one match; when no entry is effective at the required date, the operation that needed the price is rejected with `ERR_PRICE_MASTER_GAP` (422).

### 2.7. Provisional Estimates versus Final Pricing

Every repair line is priced twice. The **provisional** reading is taken at estimate time: the price entry effective at the current logical-clock date is resolved, and the line's `estimate_labor_cents` is the entry's `standard_labor_hours` multiplied by the entry's shop `labor_rate_cents_per_hour`, rounded half up to whole cents. The line's `estimate_material_cents` is the sum, over its `planned_parts`, of each planned quantity multiplied by the referenced part's `unit_price_cents`. The line's `estimate_total_cents` is the sum of the two components, and the work order's `estimate_total_cents` is the sum over its lines. The provisional reading never uses the mobile rate and never includes the trip surcharge.

The **final** reading is taken when the quality gate passes: the price entry effective at the work order's completion date is resolved — which may be a different entry than the estimate used if a window boundary was crossed mid-repair — and the labor rate is the entry's `mobile_labor_rate_cents_per_hour` when the work order's `routing` is `MOBILE`, otherwise its `labor_rate_cents_per_hour`. The line's `final_labor_cents` is its `actual_labor_hours` multiplied by that rate, rounded half up to whole cents; `final_material_cents` is the sum, over `actual_parts`, of each consumed quantity multiplied by the part's `unit_price_cents`; `final_total_cents` is the sum of the two. The work order's `final_total_cents` is the sum over its lines.

All monetary values in the system are integer cents; every multiplication that produces a fractional cent is rounded half up to whole cents at the point the rule specifies. Percentages such as `owner_pct` are integers.

### 2.8. AAR Responsibility Determination

Financial responsibility is decided per repair line at submission time by an ordered decision table; the first rule that matches wins and no later rule is consulted:

- **Rule 1** — if the defect's `cause_code` is `HANDLING_DAMAGE`, the line belongs to the handling line: `responsible_party` is `HANDLING_LINE` and `owner_pct` is 0.
- **Rule 2** — if the price master entry the line resolved to has `shared_split` true, responsibility is `SHARED` with an `owner_pct` of 50, regardless of any defect-group consideration.
- **Rule 3** — if the defect's `defect_group` is `SAFETY_APPLIANCE`, responsibility is `OWNER` with an `owner_pct` of 100.
- **Rule 4** — if the defect's `defect_group` is `WHEELSET`, `AIR_HOSE`, or `COUPLER`, responsibility is `OWNER` with an `owner_pct` of 100.
- **Rule 5** — if the defect's `defect_group` is `STRUCTURAL` and the elapsed time from the railcar's `arrived_at` to the source inspection's `completed_at` is at most 24 hours, measured at three-decimal hour precision, the damage is treated as interchange damage: responsibility is `HANDLING_LINE` with an `owner_pct` of 0.
- **Rule 6** — otherwise responsibility defaults to `OWNER` with an `owner_pct` of 100.

The work order's own `responsible_party` is then determined by money: the owner's aggregate is the sum of line `estimate_total_cents` over every line whose `owner_pct` is at least 50; the handling line's aggregate is the remainder of the estimate total; the party holding the larger aggregate becomes the work order's `responsible_party`, and a tie resolves to `OWNER`. The work order's `owner_share_pct` summarizes this split at the work-order level as the owner-responsible share of the estimate total, computed per line rather than by the majority aggregate above: each line's owner-responsible amount is its `estimate_total_cents` multiplied by its `owner_pct` and divided by 100, rounded half up to whole cents; `owner_share_pct` is the sum of those per-line amounts as a percentage of the work order's `estimate_total_cents`, rounded half up to a whole percent — yielding 100 when every line is owner-responsible and 0 when none is. When the work order's `estimate_total_cents` is zero, `owner_share_pct` is 100.

### 2.9. Parts Inventory Invariants

Each part in the crib tracks `on_hand_qty` (physical stock), `reserved_qty` (stock committed to authorized work orders, starting at 0), and the derived `available_qty`, which always equals `on_hand_qty` minus `reserved_qty` and must never go negative. Four operations move these quantities. **Reserving** at authorization requires `available_qty` to be at least the planned quantity for every planned part — any shortfall rejects the authorization with `ERR_PART_STOCK_INSUFFICIENT` (409) — and then increases `reserved_qty` by each planned quantity. **Consuming** at quality-gate pass decreases `on_hand_qty` by the consumed quantity and decreases `reserved_qty` by the planned quantity, leaving `available_qty` unchanged by the consumption itself. **Releasing** on cancellation or rejection decreases `reserved_qty` by the planned quantity, restoring availability. **Adjusting** through the parts desk applies a signed `delta_qty` to `on_hand_qty` — positive to restock, negative to write off — and is rejected with `ERR_PART_STOCK_INSUFFICIENT` when the resulting `on_hand_qty` would fall below `reserved_qty`; each adjustment records a `reason`.

A part's `status` is computed: `DEPLETED` when `on_hand_qty` is exactly zero, otherwise `REORDER_NEEDED` when `available_qty` is less than or equal to `reorder_threshold` — equality counts — and otherwise `ACTIVE`. Status is recomputed on every reservation, consumption, release, and adjustment.

### 2.10. Party Ledgers, Net Posting, and Credit Watch

The shop keeps one ledger per CarOwner and one per HandlingLine, each carried as `outstanding_balance_cents` starting at zero when the party is registered. Money posts to these ledgers at exactly two moments in the Billing Repair Card lifecycle. At acceptance — manual or deemed — the owner's balance increases by the card's `owner_total_cents` minus the owner-responsible share of accepted counter-bill credits, and the handling line's balance increases by `handling_line_total_cents` minus the handling share of those credits. This is deliberately a net posting: counter-bills always resolve before acceptance, so the credit is netted into the acceptance posting rather than posted separately, and counter-bill acceptance itself never touches the ledgers. At settlement, each balance decreases by the same net party share, returning the ledgers toward zero. Honored warranty credits decrease each party's balance by that party's share of the credit at honor time.

A CarOwner whose `outstanding_balance_cents` rises strictly above the shop's `owner_watch_threshold_cents` — defaulting to one million cents — flips to `CREDIT_WATCH`; at or below the threshold the owner is `ACTIVE`. The status is computed from the balance, not stored by hand.

### 2.11. Common Resource Properties and Optimistic Concurrency Control

Every resource in the system carries four system-managed fields: `id`, a server-minted UUID with no type prefix; `created_at`, an ISO 8601 UTC timestamp with three fractional digits recorded at creation; `updated_at`, refreshed on every mutation; and `version`, an integer that increments by one on every mutation of the resource. Derived-field recomputation — a recomputed part `status`, a flipped `current_posture` being read, a bumped `reopened_count` — accompanies mutation of the owning resource and follows the same `updated_at`/`version` discipline.

Four write operations are guarded by optimistic concurrency control, and each names the parent whose version it pins:

- Creating a work order requires `expected_railcar_version` carrying the client's last observed `version` of the target Railcar. If the railcar's version has advanced since that observation — for example because another writer's create landed and bumped it — the create is rejected with `ERR_STALE_RAILCAR_VERSION` (412), since the new work order would otherwise supersede a draft the client never saw.
- Authorizing a work order requires `expected_work_order_version` matching the work order's current `version`, so approval pins the exact estimate version the responsible party reviewed; a mismatch is rejected with `ERR_STALE_WORK_ORDER_VERSION` (412).
- Revising an estimate requires `expected_work_order_version` matching the work order's current `version`; a mismatch is rejected with `ERR_STALE_WORK_ORDER_VERSION` (412), so two successive re-pricing passes cannot silently interleave.
- Creating a draft Billing Repair Card requires `expected_work_order_version` matching the work order's current `version`; a mismatch is rejected with `ERR_STALE_WORK_ORDER_VERSION` (412), because draft creation supersedes an existing draft and bumps the work order's version.

Endpoints not listed here take no version field at all. Any operation that mutates a work order — adding a line, submitting, authorizing, rejecting, revising, assigning a slot, dispatching, starting, completing, quality review, cancellation — increments the work order's `version` by one, as does creating a draft Billing Repair Card against it. Creating a work order increments the host Railcar's `version` by one, and starting shop work moves the car to `IN_SHOP` and likewise increments the Railcar's `version`.

### 2.12. Request Validation Order and Nested Resource Retrieval

When several validations could reject the same request, the server evaluates them in a fixed order so the caller always sees the earliest applicable failure: first the presence and validity of `X-User-ID` and `X-User-Role` (else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`, 400); second whether the caller's role is permitted on the endpoint (else `ERR_FORBIDDEN_FOR_ROLE`, 403); third the scoped party and filer checks behind `ERR_RESPONSIBILITY_MISMATCH` (403); fourth segregation of duties on the quality gate (else `ERR_SEGREGATION_OF_DUTIES`, 403); fifth the existence of path resources (else `ERR_NOT_FOUND`, 404); sixth the existence of body-supplied references (else `ERR_REFERENCE_NOT_FOUND`, 404); seventh the optimistic-concurrency version match (else `ERR_STALE_RAILCAR_VERSION` or `ERR_STALE_WORK_ORDER_VERSION`, 412); eighth whether the target resource is in a from-state of the requested transition (else `ERR_INVALID_STATE_TRANSITION`, 409); ninth the cross-entity state guards (`ERR_INSPECTION_NOT_COMPLETED`, `ERR_WORK_ORDER_NOT_COMPLETED`, `ERR_CAR_NOT_IN_SHOP`, `ERR_OPEN_WORK_ORDERS`, `ERR_INSPECTION_LOCKED`, all 409); tenth the condemnable-defect safety gate on departure (`ERR_UNRESOLVED_SAFETY_DEFECT`, 409); eleventh code referential integrity (`ERR_INVALID_DEFECT_CODE`, `ERR_PRICE_MASTER_GAP`, both 422); twelfth the temporal rules (`ERR_SLOT_OVERLAP`, `ERR_SLOT_IN_PAST`, `ERR_PRICE_WINDOW_OVERLAP`, `ERR_COUNTER_BILL_WINDOW_CLOSED`, `ERR_WARRANTY_WINDOW_EXPIRED`, all 409); thirteenth the business constraints (`ERR_SHOP_AT_CAPACITY`, `ERR_SLOT_WINDOW_TOO_SHORT`, `ERR_MOBILE_ROUTE_NOT_ELIGIBLE`, `ERR_PART_STOCK_INSUFFICIENT`, `ERR_BRC_ALREADY_ACTIVE`, `ERR_COUNTER_BILL_ACTIVE`, `ERR_WARRANTY_CLAIM_ACTIVE`, `ERR_WARRANTY_NOT_APPLICABLE`, `ERR_DUPLICATE_PART_NUMBER`, `ERR_DUPLICATE_WHEELSET_SERIAL`, `ERR_WORK_ORDER_NO_LINES`, all 409); and fourteenth the fiscal ceilings (`ERR_COUNTER_BILL_EXCEEDS_CEILING`, `ERR_CREDIT_EXCEEDS_REMAINING`, both 409). A malformed body, a missing required field, an invalid enum literal, a negative or zero quantity, or a slot whose `ends_at` is not after its `starts_at` is rejected with `ERR_INVALID_REQUEST` (400).

Path resources are validated left to right. When an endpoint path nests one resource under another — a defect under an inspection, an inspection under a railcar — the server confirms each identifier exists within the shop in path order and rejects with `ERR_NOT_FOUND` at the first identifier that does not resolve, before considering any deeper segment or any business rule. Body references — `inspection_id`, `slot_id`, `defect_finding_id`, the part ids inside `planned_parts` and `line_actuals`, `work_order_id`, the `brc_line_id` of each counter item, `repair_line_id`, and the `railcar_id` of a mount — are then checked and fail with `ERR_REFERENCE_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. Setting Up the Shop: Registries, Price Master, and Calendars

A `ShopAdmin` begins by creating the shop itself, supplying its display `name`, the number of repair `stalls`, and the dwell billing rate `dwell_rate_cents_per_hour`. Four configuration values take defaults when omitted: `stall_daily_hours` defaults to 8 bookable hours per stall per calendar day, `dwell_free_hours` defaults to 48 hours of free dwell after arrival, `warranty_days` defaults to ninety days of warranty coverage measured from work-order completion, `counter_window_days` defaults to thirty days during which counter-bills are accepted after a card's submission, and `owner_watch_threshold_cents` defaults to one million cents. A freshly created shop reads `current_posture` as `OPEN`.

The `ShopAdmin` then registers the parties. A car owner is registered with its `shop_id`, company `name`, and `scac_code` mark, starting at an `outstanding_balance_cents` of zero and `status` `ACTIVE`; the car-owner list can be filtered by `shop_id` and `status`. A handling line is registered with its `shop_id`, railroad `name`, and reporting `mark`, likewise starting at zero balance; its list filters by `shop_id`.

Price master entries are created per §2.6 with their full rate card — `labor_rate_cents_per_hour`, `mobile_labor_rate_cents_per_hour`, `standard_labor_hours`, `mobile_trip_surcharge_cents`, `mobile_eligible`, optional `shared_split`, and the closed window `effective_from`/`effective_to` — and overlapping windows for the same shop and `job_code` are refused with `ERR_PRICE_WINDOW_OVERLAP`. The entry list filters by `shop_id` and `job_code`.

The parts crib is stocked by the `ShopAdmin`: each part is created with `shop_id`, a `part_number` unique within the shop — duplicates are rejected with `ERR_DUPLICATE_PART_NUMBER` — a `description`, the `unit_price_cents` used in both estimates and finals, the starting `on_hand_qty`, and the `reorder_threshold`. New parts carry `reserved_qty` zero and a computed `status` per §2.9. Thereafter a `PartsClerk` restocks or writes off stock by adjustment with a signed `delta_qty` and a `reason`, subject to the reserved-quantity floor. The parts list filters by `shop_id` and `status`.

A `PartsClerk` also registers each wheelset with `shop_id`, a `serial_number` unique within the shop — duplicates fail with `ERR_DUPLICATE_WHEELSET_SERIAL` — and the latest measurements `flange_thickness_mm` and `tread_wear_mm` recorded to three decimal places; a new wheelset starts `IN_STOCK`. The wheelset list filters by `shop_id`, `status`, and `mounted_railcar_id`.

Finally the `ShopAdmin` lays out the slot calendar. Each slot is created on a `stall_id` with a half-open window from `starts_at` to `ends_at`: the window includes its start and excludes its end, so back-to-back windows on the same stall are legal. A slot whose `ends_at` is at or before the current logical time is rejected with `ERR_SLOT_IN_PAST`; one whose `ends_at` is not after its `starts_at` is rejected with `ERR_INVALID_REQUEST`. New slots are `OPEN`, and an `OPEN` slot may be moved to `BLOCKED` for maintenance by the `ShopAdmin`. The slot list filters by `shop_id`, `stall_id`, `status`, and `reserved_work_order_id`.

### 3.2. Inbound Cars, Inspections, and AAR Defect Coding

A `YardClerk` registers each inbound car with its `shop_id`, `reporting_mark`, and `car_number` — the pair is unique within the shop — plus the car's `owner_id`, `handling_line_id`, and `built_date`. Registration stamps `arrived_at` from the logical clock, sets `status` to `ARRIVED`, zeroes `shop_delay_hours`, and leaves both dwell fields — `projected_dwell_charge_cents` and `dwell_charge_cents` — null until routing and departure produce them. The railcar list filters by `shop_id`, `owner_id`, `handling_line_id`, and `status`.

A `CarInspector` opens an inspection on a registered car; the inspection starts `IN_PROGRESS` and records the inspector's header identity in `inspector_user_id`. Against an open inspection the inspector files defect findings, each carrying an `aar_defect_code` in the format AAR-NNNN, a `defect_group` of `WHEELSET`, `AIR_HOSE`, `COUPLER`, `SAFETY_APPLIANCE`, `STRUCTURAL`, `BRAKE_BEAM`, `DOOR`, or `OTHER`, a `cause_code` of `WEAR`, `HANDLING_DAMAGE`, `ACCIDENT`, or `UNKNOWN`, a `severity` of `MINOR`, `MAJOR`, or `CONDEMNABLE`, and a free-text `location` such as "B-end truck". A malformed code or an invalid enum literal is rejected with `ERR_INVALID_DEFECT_CODE` (422). Findings start `OPEN`; the findings list filters by `status` and `severity`.

Completion stamps `completed_at` from the logical clock and moves the inspection to `COMPLETED`; completion is accepted from either `IN_PROGRESS` or `REOPENED`, and any other state fails with `ERR_INVALID_STATE_TRANSITION`. A `RepairForeman` may later reopen a `COMPLETED` inspection — provided no work order referencing it is currently `PENDING_AUTHORIZATION` or `AUTHORIZED`, a lock whose violation is rejected with `ERR_INSPECTION_LOCKED` — which moves it to `REOPENED` and increments `reopened_count`, starting from zero. The `COMPLETED` → `REOPENED` → `COMPLETED` loop may repeat while the inspection is unlocked. A finding that no repair line references may also be declined by a `RepairForeman`, moving the defect addressed by `defectId` from `OPEN` to `DECLINED`; a finding already referenced by a line cannot be declined.

### 3.3. Building the Work Order: Lines, Estimation, and Submission

With an inspection `COMPLETED`, a `RepairForeman` creates a work order by supplying `railcar_id`, the source `inspection_id`, the `routing` — `SHOP` or `MOBILE` — and the concurrency token `expected_railcar_version` per §2.11. Creation is refused when the day's posture is `FULL` (`ERR_SHOP_AT_CAPACITY`), when the referenced inspection is not `COMPLETED` (`ERR_INSPECTION_NOT_COMPLETED`), or when the railcar version is stale. The new work order opens with `auth_status` `DRAFT` and `exec_status` `NOT_STARTED`, records the foreman's header identity in `created_by_user_id`, starts `rework_count` at zero, and bumps the host railcar's `version` by one. If the railcar already had a work order in `DRAFT`, that draft is superseded on the spot: its `auth_status` and `exec_status` both move to `CANCELLED`. The work-order list filters by `railcar_id`, `inspection_id`, `assigned_slot_id`, `auth_status`, and `exec_status`.

Repair lines are added while the work order is `DRAFT`. Each line references the `defect_finding_id` it repairs and the AAR `job_code` to price, and may carry `planned_parts` — a list of tuples pairing a `part_item_id` with a `quantity`. Adding a line resolves the price master entry effective at the current logical-clock date per §2.6 — no effective entry means `ERR_PRICE_MASTER_GAP` — and prices the line provisionally per §2.7, recording the resolved entry on the line as `price_master_entry_id` and setting `estimate_labor_cents`, `estimate_material_cents`, and `estimate_total_cents`. The new line starts `ESTIMATED`, the referenced finding moves `OPEN` → `ESTIMATED`, the work order's `estimate_total_cents` is recomputed as the sum over its lines, and the work order's `version` increments. Repair lines are readable individually or through the cross-work-order line list, which filters by `price_master_entry_id`, `defect_finding_id`, and `status`.

Submission moves `auth_status` from `DRAFT` to `PENDING_AUTHORIZATION` and is itself guarded: the work order must still be `DRAFT`, the source inspection must still be `COMPLETED` — an inspection reopened after lines were drafted blocks submission with `ERR_INSPECTION_NOT_COMPLETED` — at least one line must exist (`ERR_WORK_ORDER_NO_LINES`), and a `MOBILE`-routed work order requires every line's price entry to be `mobile_eligible`, else `ERR_MOBILE_ROUTE_NOT_ELIGIBLE`. On submission the system runs the responsibility determination of §2.8 per line — stamping each line's `responsible_party` and `owner_pct` — and then sets the work order's `responsible_party` and `owner_share_pct` from the estimate sums. Submission increments the work order's `version`.

### 3.4. Authorization, Estimate Revision, and Rejection

Authorization is performed by the financially responsible party identified at submission: a `CarOwnerRep` matching the car's `owner_id` when `responsible_party` is `OWNER` or `SHARED`, or a `HandlingLineRep` matching the car's `handling_line_id` when it is `HANDLING_LINE`; any other caller is refused with `ERR_RESPONSIBILITY_MISMATCH`. The request carries `expected_work_order_version`, and if the work order's `version` has advanced past the estimate the party reviewed, authorization is rejected with `ERR_STALE_WORK_ORDER_VERSION` — approval pins the exact estimate version that was reviewed. Authorization requires the work order to be `PENDING_AUTHORIZATION`, and it enforces parts availability: for every planned part on every line, `available_qty` must be at least the planned quantity, or the authorization fails with `ERR_PART_STOCK_INSUFFICIENT` and nothing is reserved. A successful authorization stamps `authorized_at` from the logical clock, moves `auth_status` to `AUTHORIZED`, cascades every line `ESTIMATED` → `AUTHORIZED` and every referenced finding `ESTIMATED` → `AUTHORIZED`, reserves all planned parts by increasing each part's `reserved_qty`, recomputes each touched part's `status` — which may flip `ACTIVE` → `REORDER_NEEDED` when availability falls to the threshold — and increments the work order's `version`.

While the work order waits `PENDING_AUTHORIZATION`, the foreman may re-estimate it: every line's price entry is re-resolved against the price master at the current logical-clock date — a gap for any line fails the whole operation with `ERR_PRICE_MASTER_GAP` — and the estimate fields and work-order `estimate_total_cents` are recomputed. This self-loop requires `expected_work_order_version` matching the current `version`, increments the `version` by one, and thereby leaves any authorization attempt carrying the pre-revision version stale.

The responsible party may instead reject the estimate, optionally supplying a `reason`. Rejection requires the same party match as authorization, moves `auth_status` to `REJECTED`, cascades `exec_status` to `CANCELLED`, moves every line to `CANCELLED`, returns every `ESTIMATED` finding to `OPEN`, and increments the work order's `version`.

### 3.5. Routing, Execution, and the Quality Gate

An `AUTHORIZED` work order routed `SHOP` is queued by reserving a slot: the foreman supplies a `slot_id`, the slot must be `OPEN`, and its half-open window must not overlap any other slot on the same stall that is `RESERVED` or `OCCUPIED` — overlap is evaluated on half-open intervals, so a window ending exactly when another begins is adjacency, not overlap, and is allowed; a true overlap is rejected with `ERR_SLOT_OVERLAP`. The slot's window in hours must also cover the sum of the lines' `standard_labor_hours`, else `ERR_SLOT_WINDOW_TOO_SHORT`. Success moves `exec_status` `NOT_STARTED` → `SHOP_QUEUED`, moves the slot `OPEN` → `RESERVED`, records the slot on the work order as `assigned_slot_id` and the work order on the slot as `reserved_work_order_id`, pins the car's `projected_dwell_charge_cents` using the shop-routing projection of §3.6, and increments the work order's `version`.

An `AUTHORIZED` work order routed `MOBILE` is instead dispatched by supplying a `mobile_crew_id`, which is recorded on the work order; dispatch moves `exec_status` `NOT_STARTED` → `MOBILE_DISPATCHED`, pins the same projection using the mobile variant, and increments the `version`. A work order routed `SHOP` cannot be dispatched and one routed `MOBILE` cannot be assigned a slot — each move is an invalid state transition on the wrong routing.

Starting work moves `exec_status` from `SHOP_QUEUED` or `MOBILE_DISPATCHED` to `IN_PROGRESS`. For a shop-routed order the reserved slot moves `RESERVED` → `OCCUPIED` and the railcar moves `ARRIVED` → `IN_SHOP`, incrementing the Railcar's `version`; mobile starts carry no slot or car cascade. When the work is done the foreman reports completion with `line_actuals` covering every non-cancelled line — an incomplete report is rejected with `ERR_INVALID_REQUEST` — which records each line's `actual_labor_hours` and `actual_parts`, stamps `qa_review_entered_at` from the logical clock, moves `exec_status` to `QA_REVIEW`, and increments the `version`.

The quality gate is held by a `QualityInspector`, who submits a `result` of pass or fail with optional `notes`. Segregation of duties is enforced: the reviewer's `X-User-ID` must differ from the work order's `created_by_user_id`, or the review is rejected with `ERR_SEGREGATION_OF_DUTIES` (403). A **pass** stamps `completed_at`, accrues the hours from `qa_review_entered_at` to now into the railcar's `shop_delay_hours`, moves `exec_status` to `COMPLETED`, and then cascades: every line moves `AUTHORIZED` → `FINALIZED` and is re-priced at final rates per §2.7, setting `final_labor_cents`, `final_material_cents`, and `final_total_cents`; every `AUTHORIZED` finding moves to `REPAIRED`; planned parts are consumed per §2.9, which may flip a part to `DEPLETED`; a shop routing's slot moves `OCCUPIED` → `RELEASED` with `reserved_work_order_id` cleared; and when no sibling work order of the same railcar remains outside `COMPLETED` or `CANCELLED`, the car moves `IN_SHOP` → `READY_FOR_DEPARTURE`. A **fail** instead returns `exec_status` to `IN_PROGRESS` for rework, increments `rework_count`, and still accrues the QA interval into `shop_delay_hours` — the shop owns that delay either way. Either outcome increments the work order's `version`, and the `QA_REVIEW` → `IN_PROGRESS` loop may repeat.

A `RepairForeman` may cancel a work order — with an optional `reason` — only while no work has started, that is while `exec_status` is `NOT_STARTED`, `SHOP_QUEUED`, or `MOBILE_DISPATCHED`; this holds whether `auth_status` is `DRAFT` or `AUTHORIZED`, and an order already `IN_PROGRESS` or later cannot be cancelled. Cancellation is compensating: `auth_status` and `exec_status` move to `CANCELLED`, lines move to `CANCELLED` from `ESTIMATED` or `AUTHORIZED`, findings return to `OPEN` from `ESTIMATED` or `AUTHORIZED`, a reserved slot is released to `RELEASED` with `reserved_work_order_id` cleared, and every part reservation is released with status recomputation per §2.9.

While a car is `IN_SHOP`, a `RepairForeman` may mount an `IN_STOCK` wheelset onto it by supplying the target `railcar_id`; mounting against a car in any other status is refused with `ERR_CAR_NOT_IN_SHOP`. Mounting moves the wheelset to `MOUNTED` and records `mounted_railcar_id`; removal moves it to `REMOVED` and clears `mounted_railcar_id`.

### 3.6. Departure, Dwell Accounting, and Wheelset Evaluation

Departure is a `YardClerk` action with a hard safety gate. From `ARRIVED`, departure additionally requires that no work order of the car remains outside `COMPLETED` or `CANCELLED` — a car with open work cannot leave, and the attempt is rejected with `ERR_OPEN_WORK_ORDERS`. From either `ARRIVED` or `READY_FOR_DEPARTURE`, the safety gate forbids departure while any finding on the car's inspections has `severity` `CONDEMNABLE` and a status outside `REPAIRED` or `DECLINED`; a blocked departure is rejected with `ERR_UNRESOLVED_SAFETY_DEFECT`. A successful departure stamps `departed_at` from the logical clock, moves the car to `DEPARTED`, and runs the actual dwell calculation below, storing the result in `dwell_charge_cents`.

Dwell is billed on net car hours. The **actual** variant, run at departure, takes the car's actual hours as the fractional elapsed time — at two decimal places — from `arrived_at` to `departed_at`; subtracts the shop's `dwell_free_hours` allowance and the car's accumulated `shop_delay_hours`; keeps the greater of that difference and zero as the billable hours; and multiplies billable hours by `dwell_rate_cents_per_hour`, rounding half up to whole cents. When actual hours minus shop delay is less than or equal to the free allowance the charge is exactly zero — only a strictly greater excess bills. The **projected** variant, pinned earlier at slot reservation or mobile dispatch, is forward-looking: the projected release instant is the reserved slot's `ends_at` for `SHOP` routing, or the current logical time plus the sum of the lines' `standard_labor_hours` for `MOBILE` routing; projected billable hours are the greater of zero and the elapsed hours from `arrived_at` to that release instant minus the free allowance — no shop delay is subtracted, since none has accrued yet — and the projected charge is the rate multiplication rounded half up, stored as `projected_dwell_charge_cents`. A dwell-summary read on any car recomputes the actual variant live at read time and returns `actual_dwell_hours`, `shop_delay_hours`, `billable_hours`, and `dwell_charge_cents` alongside the pinned `projected_dwell_charge_cents`.

Removed wheelsets are evaluated by a `QualityInspector`, who records fresh `flange_thickness_mm` and `tread_wear_mm` measurements at three-decimal millimeter precision. The condemnation rule is a hard boundary: a wheelset is condemned when its flange thickness is at most 28.0 millimeters or its tread wear is at least 9.5 millimeters — a flange of exactly 28.0 or a tread of exactly 9.5 condemns. A `REMOVED` wheelset inside both limits — flange greater than 28.0 and tread under 9.5 — is reclaimed to `IN_STOCK`; a `REMOVED` wheelset beyond either limit moves to `CONDEMNED`; and an `IN_STOCK` wheelset evaluated beyond either limit is likewise condemned. The `IN_STOCK` → `MOUNTED` → `REMOVED` → `IN_STOCK` reclaim loop is cyclic, while `CONDEMNED` is terminal.

### 3.7. Billing Repair Cards: Drafting, Submission, Acceptance, and Settlement

Once a work order's `exec_status` is `COMPLETED`, a `BillingClerk` drafts a Billing Repair Card against it by supplying the `work_order_id` and the concurrency token `expected_work_order_version` per §2.11. Drafting requires the work order's execution to be `COMPLETED` — otherwise `ERR_WORK_ORDER_NOT_COMPLETED` — and refuses with `ERR_BRC_ALREADY_ACTIVE` when a non-draft, non-terminal card already exists for the work order; such a card must be withdrawn before a new draft can be created. When an existing card for the same work order is still `DRAFT`, drafting a new one supersedes it: the old card moves to `SUPERSEDED` and the new card records it in `supersedes_brc_id`. The new card starts `DRAFT`, snapshots every `FINALIZED` repair line into a card line carrying the line's `job_code` and a `final_amount_cents` equal to the line's `final_total_cents`, runs the aggregation below, and bumps the work order's `version` by one. The card list filters by `work_order_id`, `status`, and `supersedes_brc_id`; card lines are listed per card or across cards filtered by `repair_line_id` and `brc_id`.

Card totals are aggregated with a pinned rounding order — per component, per line, then summed; never sum-then-round. Each card line's `owner_share_cents` is its `final_amount_cents` multiplied by the repair line's `owner_pct` and divided by 100, rounded half up to whole cents; the `handling_share_cents` is the remainder, the final amount minus the owner share. For a `MOBILE`-routed work order, the card's `mobile_surcharge_cents` is the `mobile_trip_surcharge_cents` of the price entry used by the earliest-created repair line — ties broken by line creation order — and is zero for `SHOP` routing. The `submitted_total_cents` is the sum of line final amounts plus the surcharge. The `owner_total_cents` is the sum of line owner shares, plus the surcharge when the work order's `responsible_party` is `OWNER` or `SHARED`; the `handling_line_total_cents` is whatever remains of the submitted total. The `net_settled_cents` anchors the card: the submitted total minus the sum of accepted counter credits, recomputed whenever credits land.

Submitting a `DRAFT` card moves it to `SUBMITTED`, stamps `submitted_at` from the logical clock, computes `dispute_window_ends_at` as `submitted_at` plus the shop's `counter_window_days`, and pins `submitted_total_cents`, `owner_total_cents`, and `handling_line_total_cents` at their submitted values. Acceptance — by the responsible party under the party-match rule of §2.1 — requires the card to be `SUBMITTED` with no counter-bill in `OPEN` or `REBUTTED`, else `ERR_COUNTER_BILL_ACTIVE`; acceptance posts the net balances of §2.10 and moves the card to `ACCEPTED`. The same transition happens without any user action when the sweep of §2.4 finds the dispute window passed with no active counters — deemed acceptance posts identical balances. Settling an `ACCEPTED` card moves it to `SETTLED` and unwinds the same net party shares from the ledgers. A `BillingClerk` may withdraw a card while it is `DRAFT`, or while it is `SUBMITTED` provided no counter-bill is `OPEN` or `REBUTTED` — otherwise `ERR_COUNTER_BILL_ACTIVE` — moving it to `WITHDRAWN`. The `SUBMITTED` ↔ `DISPUTED` cycle described in §3.8 may repeat across counter-billing rounds before acceptance.

### 3.8. Counter-Bills and the Dispute Cycle

Either responsible party may file a counter-bill against a card in `SUBMITTED` or `DISPUTED`, provided the filing lands within the dispute window — a filing after `dispute_window_ends_at` is rejected with `ERR_COUNTER_BILL_WINDOW_CLOSED` — and no other counter-bill on the card is `OPEN` or `REBUTTED`, else `ERR_COUNTER_BILL_ACTIVE`. The filing payload is a list of `items`, each naming a `brc_line_id`, a `counter_amount_cents`, and a `reason`. Filing records the filer's role in `filed_by_role`, the filer's header identity in `filed_by_id`, and the clock time in `filed_at`; sets `total_countered_cents` to the sum of item amounts; starts the counter-bill `OPEN`; and moves the host card `SUBMITTED` → `DISPUTED`. Counter-bill lists filter by `status`.

Two ceilings guard every filing, evaluated in this order: the aggregate ceiling first, then the per-line remainder. The aggregate ceiling forbids the running total from exceeding 60 percent of the card: the sum of `total_countered_cents` over all `ACCEPTED` counter-bills on the card, plus all `OPEN` or `REBUTTED` ones, plus this bill's own total, must be less than or equal to the floor of 0.60 multiplied by `submitted_total_cents` — landing exactly at the cap is allowed — and a breach is rejected with `ERR_COUNTER_BILL_EXCEEDS_CEILING`. The per-line check then requires each item's `counter_amount_cents` to be no more than the referenced card line's `final_amount_cents` minus its `accepted_credit_cents` minus its `warranty_credit_cents`, else `ERR_CREDIT_EXCEEDS_REMAINING`.

The shop answers through a `BillingClerk`. Accepting a counter-bill — from either `OPEN` or `REBUTTED` — moves it to `ACCEPTED` and runs a three-hop cascade: first each item's amount is added to its card line's `accepted_credit_cents` (starting from zero); then the card's `net_settled_cents` is recomputed as `submitted_total_cents` minus the sum of accepted credits; and finally, when no active counters remain, the card returns `DISPUTED` → `SUBMITTED`. Balances are deliberately untouched here, because counters always resolve before acceptance and the credit is netted into the eventual acceptance posting. Rebutting instead moves an `OPEN` counter to `REBUTTED` with an optional `rebuttal_note`. The filer — and only the filer, matched by `filed_by_id` — may then revise a `REBUTTED` counter back to `OPEN` with a replacement `items` list, provided the dispute window is still open; revision recomputes `total_countered_cents` and re-runs both ceiling checks. The filer may also withdraw an `OPEN` or `REBUTTED` counter outright, moving it to `WITHDRAWN`, and the sweep of §2.4 expires any counter still active once the dispute window plus a grace of `counter_window_days` has passed, moving it to `EXPIRED`; either resolution flips the card `DISPUTED` → `SUBMITTED` when it was the last active counter. The `OPEN` → `REBUTTED` → `OPEN` negotiation cycle may repeat within the window.

### 3.9. Warranty Claims and Appeals

When a completed repair fails inside its warranty window, the responsible party files a warranty claim naming the failed `repair_line_id`, the `failure_defect_group` of the new failure, a `description`, and the `claimed_rework_cost_cents`. Eligibility is checked at filing: the claim must land no later than the work order's `completed_at` plus the shop's `warranty_days` — the boundary day itself is included, and anything later is rejected with `ERR_WARRANTY_WINDOW_EXPIRED`; the referenced repair line must be `FINALIZED` and the `failure_defect_group` must match the original defect's `defect_group`, with either violation rejected as `ERR_WARRANTY_NOT_APPLICABLE`; and no other claim on the same line may be `FILED` or `VALIDATED`, else `ERR_WARRANTY_CLAIM_ACTIVE`. A valid filing starts `FILED` with `filed_by_role` and `filed_by_id` recorded and `appeal_count` at zero; the claim list filters by `shop_id`, `repair_line_id`, and `status`.

A `QualityInspector` then validates the claim — `FILED` → `VALIDATED` — or denies it outright; denial is possible from either `FILED` or `VALIDATED` and moves the claim to `DENIED` with an optional `reason`. Honoring is a billing act: a `BillingClerk` honors a `VALIDATED` claim, which computes `credit_cents` and moves the claim to `HONORED`. The credit is the smaller of two amounts: the repair line's `final_total_cents` minus the card line's `accepted_credit_cents` and minus any `warranty_credit_cents` previously honored on that line, on the one hand; and the claim's `claimed_rework_cost_cents` on the other. The honored credit is added to the card line's `warranty_credit_cents` when a card line exists for the repair line, and it splits between the ledgers by the line's `owner_pct`: the owner's share is the credit multiplied by `owner_pct` and divided by 100, rounded half up to whole cents, the handling line receives the remainder, and each party's `outstanding_balance_cents` decreases by its share.

A denied claim is not final while the warranty window lasts: the original filer — matched by `filed_by_id` — may appeal a `DENIED` claim, moving it back to `FILED` with an optional `note` and incrementing `appeal_count`, provided the appeal still lands within the window; a late appeal is rejected with `ERR_WARRANTY_WINDOW_EXPIRED`. The `FILED` → `DENIED` → `FILED` appeal cycle may repeat until the window closes.

## 4. Endpoint Definitions

Operations that create a new resource — a shop, party, price entry, part, wheelset, slot, railcar, inspection, defect finding, work order, repair line, Billing Repair Card, counter-bill, or warranty claim — return `201 Created`. Operations that act on an existing resource, including all state-transition actions, the clock set, the sweep, stock adjustment, and quality review, return `200 OK`. Request payloads, computed fields, side effects, and guard conditions are defined by the narratives of §2 and §3; this table is the routing contract only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the logical clock | ShopAdmin |
| POST | `/shops` | Create a Shop | ShopAdmin |
| GET | `/shops/{id}` | Get a Shop including computed current_posture | Any |
| POST | `/shops/{id}/sweep` | Apply time-based transitions: counter expiry, then deemed BRC acceptance | ShopAdmin |
| POST | `/car-owners` | Register a CarOwner in a shop | ShopAdmin |
| GET | `/car-owners` | List CarOwners | Any |
| GET | `/car-owners/{id}` | Get a CarOwner | Any |
| POST | `/handling-lines` | Register a HandlingLine in a shop | ShopAdmin |
| GET | `/handling-lines` | List HandlingLines | Any |
| GET | `/handling-lines/{id}` | Get a HandlingLine | Any |
| POST | `/price-master-entries` | Create a price master entry with a non-overlapping effective window | ShopAdmin |
| GET | `/price-master-entries` | List price master entries | Any |
| GET | `/price-master-entries/{id}` | Get a price master entry | Any |
| POST | `/parts` | Create a PartItem | ShopAdmin |
| GET | `/parts` | List PartItems | Any |
| GET | `/parts/{id}` | Get a PartItem | Any |
| POST | `/parts/{id}/adjust` | Restock or write off stock by a signed delta | PartsClerk |
| POST | `/wheelsets` | Register a Wheelset | PartsClerk |
| GET | `/wheelsets` | List Wheelsets | Any |
| GET | `/wheelsets/{id}` | Get a Wheelset | Any |
| POST | `/wheelsets/{id}/mount` | Mount an IN_STOCK wheelset onto an IN_SHOP railcar | RepairForeman |
| POST | `/wheelsets/{id}/remove` | Remove a MOUNTED wheelset | RepairForeman |
| POST | `/wheelsets/{id}/evaluate` | Record measurements and apply the condemnation rule | QualityInspector |
| POST | `/shop-slots` | Create a half-open bookable slot window on a stall | ShopAdmin |
| GET | `/shop-slots` | List ShopSlots | Any |
| GET | `/shop-slots/{id}` | Get a ShopSlot | Any |
| POST | `/shop-slots/{id}/block` | Block an OPEN slot for maintenance | ShopAdmin |
| POST | `/railcars` | Register an inbound railcar | YardClerk |
| GET | `/railcars` | List Railcars | Any |
| GET | `/railcars/{id}` | Get a Railcar | Any |
| POST | `/railcars/{id}/depart` | Depart a railcar and compute the actual dwell charge | YardClerk |
| GET | `/railcars/{id}/dwell-summary` | Live dwell read with the pinned projection | Any |
| POST | `/railcars/{id}/inspections` | Open an inspection on a railcar | CarInspector |
| GET | `/railcars/{id}/inspections` | List inspections of a railcar | Any |
| GET | `/inspections/{id}` | Get an Inspection | Any |
| POST | `/inspections/{id}/defects` | Add an AAR-coded defect finding | CarInspector |
| GET | `/inspections/{id}/defects` | List defect findings of an inspection | Any |
| POST | `/inspections/{id}/defects/{defectId}/decline` | Decline an unreferenced OPEN finding | RepairForeman |
| POST | `/inspections/{id}/complete` | Complete an inspection | CarInspector |
| POST | `/inspections/{id}/reopen` | Reopen a COMPLETED inspection when unlocked | RepairForeman |
| POST | `/work-orders` | Create a WorkOrder from a COMPLETED inspection (OCC on the railcar) | RepairForeman |
| GET | `/work-orders` | List WorkOrders | Any |
| GET | `/work-orders/{id}` | Get a WorkOrder | Any |
| POST | `/work-orders/{id}/lines` | Add a repair line while DRAFT | RepairForeman |
| GET | `/work-orders/{id}/lines` | List repair lines of a work order | Any |
| GET | `/repair-lines/{id}` | Get a RepairLine | Any |
| GET | `/repair-lines` | List RepairLines across work orders | Any |
| POST | `/work-orders/{id}/submit` | Submit for authorization and run responsibility determination | RepairForeman |
| POST | `/work-orders/{id}/authorize` | Responsible party authorizes the pinned estimate version | CarOwnerRep, HandlingLineRep |
| POST | `/work-orders/{id}/reject` | Responsible party rejects the estimate | CarOwnerRep, HandlingLineRep |
| POST | `/work-orders/{id}/revise-estimate` | Re-resolve prices at the current date while pending (OCC) | RepairForeman |
| POST | `/work-orders/{id}/assign-slot` | Reserve a slot for a SHOP work order | RepairForeman |
| POST | `/work-orders/{id}/dispatch` | Dispatch a mobile crew for a MOBILE work order | RepairForeman |
| POST | `/work-orders/{id}/start` | Begin queued or dispatched work | RepairForeman |
| POST | `/work-orders/{id}/complete` | Report per-line actuals and enter QA review | RepairForeman |
| POST | `/work-orders/{id}/qa-review` | Quality gate with segregation of duties | QualityInspector |
| POST | `/work-orders/{id}/cancel` | Cancel a work order that has not started, compensating slots and parts | RepairForeman |
| POST | `/billing-repair-cards` | Draft a Billing Repair Card from a COMPLETED work order (OCC on the work order) | BillingClerk |
| GET | `/billing-repair-cards` | List BillingRepairCards | Any |
| GET | `/billing-repair-cards/{id}` | Get a BillingRepairCard | Any |
| GET | `/billing-repair-cards/{id}/lines` | List lines of a BRC | Any |
| GET | `/brc-lines/{id}` | Get a BrcLine | Any |
| GET | `/brc-lines` | List BrcLines across cards | Any |
| POST | `/billing-repair-cards/{id}/submit` | Submit a draft card, pinning totals and opening the dispute window | BillingClerk |
| POST | `/billing-repair-cards/{id}/accept` | Responsible party accepts a card with no active counters | CarOwnerRep, HandlingLineRep |
| POST | `/billing-repair-cards/{id}/withdraw` | Withdraw a DRAFT or SUBMITTED card with no active counters | BillingClerk |
| POST | `/billing-repair-cards/{id}/settle` | Mark an ACCEPTED card paid and unwind net balances | BillingClerk |
| POST | `/billing-repair-cards/{id}/counter-bills` | File a counter-bill within the dispute window | CarOwnerRep, HandlingLineRep |
| GET | `/billing-repair-cards/{id}/counter-bills` | List counter-bills of a BRC | Any |
| GET | `/counter-bills/{id}` | Get a CounterBill | Any |
| POST | `/counter-bills/{id}/accept` | Shop accepts a counter-bill, cascading credits | BillingClerk |
| POST | `/counter-bills/{id}/rebut` | Shop rebuts an OPEN counter-bill | BillingClerk |
| POST | `/counter-bills/{id}/revise` | Filer revises a REBUTTED counter-bill | CarOwnerRep, HandlingLineRep |
| POST | `/counter-bills/{id}/withdraw` | Filer withdraws an OPEN or REBUTTED counter-bill | CarOwnerRep, HandlingLineRep |
| POST | `/warranty-claims` | File a warranty claim against a FINALIZED repair line | CarOwnerRep, HandlingLineRep |
| GET | `/warranty-claims` | List WarrantyClaims | Any |
| GET | `/warranty-claims/{id}` | Get a WarrantyClaim | Any |
| POST | `/warranty-claims/{id}/validate` | Quality inspector validates a claim | QualityInspector |
| POST | `/warranty-claims/{id}/honor` | Billing clerk honors a VALIDATED claim and posts credit shares | BillingClerk |
| POST | `/warranty-claims/{id}/deny` | Quality inspector denies a claim | QualityInspector |
| POST | `/warranty-claims/{id}/appeal` | Filer appeals a DENIED claim within the warranty window | CarOwnerRep, HandlingLineRep |

## 5. Error Code Catalogue

Trigger conditions for each error live with the rules in §2 and §3; this catalogue is the identifier-to-status mapping only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_RESPONSIBILITY_MISMATCH` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_REFERENCE_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_RAILCAR_VERSION` | 412 Precondition Failed |
| `ERR_STALE_WORK_ORDER_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_INSPECTION_NOT_COMPLETED` | 409 Conflict |
| `ERR_INSPECTION_LOCKED` | 409 Conflict |
| `ERR_WORK_ORDER_NOT_COMPLETED` | 409 Conflict |
| `ERR_CAR_NOT_IN_SHOP` | 409 Conflict |
| `ERR_OPEN_WORK_ORDERS` | 409 Conflict |
| `ERR_UNRESOLVED_SAFETY_DEFECT` | 409 Conflict |
| `ERR_INVALID_DEFECT_CODE` | 422 Unprocessable Entity |
| `ERR_PRICE_MASTER_GAP` | 422 Unprocessable Entity |
| `ERR_SLOT_OVERLAP` | 409 Conflict |
| `ERR_SLOT_IN_PAST` | 409 Conflict |
| `ERR_PRICE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_COUNTER_BILL_WINDOW_CLOSED` | 409 Conflict |
| `ERR_WARRANTY_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_SHOP_AT_CAPACITY` | 409 Conflict |
| `ERR_SLOT_WINDOW_TOO_SHORT` | 409 Conflict |
| `ERR_MOBILE_ROUTE_NOT_ELIGIBLE` | 409 Conflict |
| `ERR_PART_STOCK_INSUFFICIENT` | 409 Conflict |
| `ERR_BRC_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_COUNTER_BILL_ACTIVE` | 409 Conflict |
| `ERR_WARRANTY_CLAIM_ACTIVE` | 409 Conflict |
| `ERR_WARRANTY_NOT_APPLICABLE` | 409 Conflict |
| `ERR_DUPLICATE_PART_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_WHEELSET_SERIAL` | 409 Conflict |
| `ERR_WORK_ORDER_NO_LINES` | 409 Conflict |
| `ERR_COUNTER_BILL_EXCEEDS_CEILING` | 409 Conflict |
| `ERR_CREDIT_EXCEEDS_REMAINING` | 409 Conflict |
