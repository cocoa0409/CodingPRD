# Interior Design PM API — Product Requirements Document

## 1. Introduction

Running an interior design studio means living simultaneously in two worlds: the creative world of mood boards, room scopes, and furniture selections, and the operational world of vendor orders, lead-time tracking, deposits, and budget reconciliation. The Interior Design PM API exists to keep those two worlds in lockstep. From the moment a client brief is captured — a budget, a billing arrangement, and a short narrative of what the client wants — through room scoping, mood-board presentation and approval, FF&E specification, procurement, install, and punch-list close-out, the system is the single authoritative record of where a project stands and how much of its budget has been committed.

The platform is built around a small set of cooperating professionals. Designers shape the creative deliverables; a procurement coordinator turns specified selections into vendor orders and shepherds them through shipping, delivery, and install; the client funds the budget, approves rooms, and raises revision requests; and a studio administrator handles onboarding, payments, holds, fee finalization, and other operational levers. Because money and creative state are deeply intertwined — placing an order commits spend, a blocking install defect can freeze a project, an approved deposit cascades across outstanding orders — the API treats budget posture as a first-class, continuously derived property rather than an afterthought. The requirements below specify exactly how every artifact moves through its lifecycle, how the design fee and budget health are computed, and how the system protects clients from acting on stale financial snapshots.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply uniformly across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must be authenticated through two mandatory HTTP headers. `X-User-ID` identifies the acting user, and `X-User-Role` declares the capacity in which they are acting. If `X-User-Role` is missing or does not name one of the recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`. When the header is present and valid but the role is not permitted to perform the requested operation — or an ownership check fails — the request is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, spelled precisely as follows: `StudioAdmin`, `Designer`, `ProcurementCoordinator`, and `Client`.

Three of these roles are operator identities not backed by any persisted entity. When `X-User-Role` is `StudioAdmin`, `Designer`, or `ProcurementCoordinator`, the `X-User-ID` value is an opaque operator identifier that the server does not compare to any entity's `id`. The server may record such an identifier where a workflow asks it to — for example, time logged by a designer carries a `designer_user_id` supplied in the request body — but it never treats the header value itself as a foreign key into a stored record.

The `Client` role is different: it is entity-backed. When `X-User-Role` is `Client`, the `X-User-ID` is the `id` of the acting `Client` record. Ownership checks on any resource that references a `Client` compare the resource's owning-client foreign key to `X-User-ID`. Concretely, a `Project` records its owning client in `client_user_id`; a `Client` may only act on (and read) a `Project` whose `client_user_id` equals their `X-User-ID`, and may only act on artifacts that belong to such a project. An ownership mismatch surfaces as `ERR_FORBIDDEN`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, may be no smaller than 1, and may be no larger than 100. The `offset` parameter sets how many items are skipped before the page begins; when omitted it defaults to 0. A `limit` or `offset` that falls outside its permitted range — or a malformed request body — is rejected with `ERR_VALIDATION`.

Unless an endpoint explicitly states otherwise, every list is returned sorted by the resource's `created_at` timestamp in ascending order.

Every list response carries the pagination bookkeeping inside the `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Identity, Timestamps, and Versioning of Resources

Most resources in the system are full first-class records that carry a common set of system-managed fields. Each such resource exposes an `id` — a server-minted UUID with no type prefix — a `created_at` timestamp written once at creation, an `updated_at` timestamp refreshed on every mutation, and an integer `version` that begins at its initial value and increments by one on every mutation. All timestamps are ISO 8601 UTC values with three fractional digits.

One entity is deliberately leaner. An `OrderLine` is an immutable join row recorded when a selection is attached to an order; it carries only `id` and `created_at`. It has no `updated_at` and no `version`, because once written it is never modified in place. Every other entity — `Project`, `Client`, `Room`, `MoodBoard`, `FFEItem`, `DesignSelection`, `Vendor`, `ProcurementOrder`, `RevisionRequest`, `PunchListItem`, `TimeEntry`, and `PaymentReceipt` — carries the full `id`/`created_at`/`updated_at`/`version` quartet.

It bears emphasizing that computed and derived fields are not exempt from versioning. When the server re-derives a project's ledger figures — its `committed_cents`, `design_fee_cents`, `budget_remaining_cents`, `budget_status`, `posture`, or `client_credit_cents` — that re-derivation is a mutation of the `Project`: its `updated_at` advances and its `version` increments by one, exactly as if a client field had been edited.

### 2.5. Nested Resource Retrieval and Existence Ordering

Many paths name a parent resource and then a child beneath it. The system validates the identifiers in a path strictly from left to right. The first identifier that does not resolve to an existing resource causes the request to be rejected immediately with `ERR_NOT_FOUND`, before any identifier further to the right is examined. Beyond mere existence, the system also confirms membership: when a path names a child under a particular parent, the child must actually belong to that parent, and a child that exists but belongs to a different parent is treated as not found and likewise yields `ERR_NOT_FOUND`. This left-to-right existence-and-membership check is the third validation gate the system applies, after authentication and authorization.

### 2.6. Validation Ordering

When several checks could reject the same request, they are evaluated in a fixed priority order so that the failure a client sees is deterministic. Authentication comes first: a missing or unrecognized `X-User-Role` yields `ERR_UNAUTHENTICATED`. Authorization comes second: a role not permitted for the operation, or an entity-backed `Client` acting on a project it does not own, yields `ERR_FORBIDDEN`. Path existence and membership come third, yielding `ERR_NOT_FOUND` as described above. Fourth comes request well-formedness: on every create or modify operation, required body fields must be present, correctly typed, and within their declared constraints — including the rule that an order's `window_end` must be strictly later than its `window_start` — with violations reported as `ERR_INVALID_REQUEST`. Only after these four gates pass does the system evaluate state-machine legality (rejecting an illegal transition for the resource's current state with `ERR_INVALID_STATE`) and then the domain-specific business rules described throughout §2 and §3. Where a single endpoint layers several business rules, the order in which those business rules fire is spelled out in the workflow narrative that governs that endpoint.

### 2.7. Monetary Values, Rounding, and Precision

All monetary figures are integer cents. Where a calculation can produce a fractional cent — most notably a trade-discounted selection line — the result is rounded to a whole number of cents using the round-half-up convention, meaning a value whose fractional part is exactly one half rounds upward. Rounding is applied at a precisely specified point for each calculation, and §3 pins those points exactly; the round-half-up rule is the universal tie-breaking convention wherever rounding occurs.

Budget utilization is the one quantity that is *not* pre-rounded. As §3 details, the comparison that assigns a project its budget tier is performed on the exact ratio of committed-plus-fee to budget, using exact rational arithmetic, so that boundary cases land in the correct tier rather than being nudged across a threshold by premature rounding.

### 2.8. The Budget Ledger and Project Posture

Every `Project` maintains a continuously reconciled budget ledger whose fields are derived, never written directly by a client. The ledger tracks `committed_cents` (spend locked in by live orders), `design_fee_cents` (the studio's fee for the engagement), `budget_remaining_cents`, a `budget_status` tier, and `client_credit_cents` (deposit money not yet allocated to any order). Whenever an event touches orders, the design fee, deposits, revisions, or punch items, the affected ledger fields are recomputed and, as a derived consequence, the project's overall `posture` is re-evaluated. The precise formulas live in §3; what matters system-wide is that these fields always reflect current reality and that recomputing them is itself a versioned mutation of the project per §2.4.

A project's `posture` is a compound gate derived from the ledger and the project's open work, taking one of three values: `OPEN`, `BUDGET_REVIEW`, or `FROZEN`. It is recomputed after every mutation that touches orders, revisions, punch items, the budget ledger, or time and fee state, and it is determined by the following priority rules, where the first matching rule wins. First, the posture is `FROZEN` if any punch item on any of the project's orders is simultaneously in status `OPEN` and of severity `BLOCKING`. Second, failing that, the posture is `FROZEN` if the project's `budget_status` is `RED`. Third, the posture is `BUDGET_REVIEW` if the `budget_status` is `AMBER`. Fourth, the posture is `BUDGET_REVIEW` if any revision request is in `SUBMITTED` or `CHANGES_REQUESTED` status. If none of those conditions hold, the posture is `OPEN`.

The posture is not merely informational; it gates operations. A `FROZEN` posture blocks three things: opening a newly placed procurement order, advancing the project into installation, and closing the project. A `BUDGET_REVIEW` posture is narrower — it blocks only the placement of new procurement orders. The error each gate raises is specified in §3 alongside the workflow it guards.

### 2.9. Cascading Reconciliation Across the Hierarchy

The system is built around a small number of operations that ripple outward. Placing an order does not merely flip the order's status — it advances every selection attached to that order, recomputes the project's committed spend, re-derives the budget tier and posture, and bumps the project's version. Cancelling or returning an order runs the same machinery in reverse, releasing committed spend, reverting selections, re-running the deposit allocation, and re-deriving posture. Approving a room accepts one mood board and supersedes its siblings. These secondary effects are an integral part of each operation's contract, not optional housekeeping; §3 enumerates every cascade for every transition, and the implementer must treat each enumerated effect as mandatory.

### 2.10. Optimistic Concurrency Control

Two write operations act on the shared project budget ledger and therefore guard against a client overwriting changes it has not observed. Both require the caller to submit `expected_project_version`, carrying the `version` of the target `Project` as the client last read it. The server compares that value against the project's current `version`; if they differ — because some other writer has advanced the project since the client's last read — the write is rejected with `ERR_STALE_VERSION` and HTTP status 412, and no change is made.

The first such operation is placing a procurement order. Placing commits the order's subtotal against the project's shared budget ledger and re-derives the budget tier and posture, so a caller holding a stale view of `committed_cents` and budget headroom must not place an order; `expected_project_version` ensures the budget gate is evaluated against the project's current committed spend rather than an outdated snapshot, and a mismatch yields `ERR_STALE_VERSION` (HTTP 412). The second is recording a client deposit. A deposit triggers the deposit waterfall, which re-allocates how much each outstanding order has been paid; a deposit recorded against a stale project version may have been computed against an order set that has since changed — an order cancelled, or a prior deposit recorded — so the resulting allocation would be wrong, and the stale-version deposit is rejected with `ERR_STALE_VERSION` (HTTP 412). No other endpoint requires a version field; only these two carry `expected_project_version`, and it is a required input for each.

## 3. Business Logic & Workflows

### 3.1. Onboarding: Clients, the Catalog, and Vendors

Before any project work begins, three kinds of reference data are established. A studio administrator registers a `Client` account by supplying a `display_name` and an `email`; the email must be unique across all clients, and a collision is rejected with `ERR_DUPLICATE`. The resulting `Client` record is what the entity-backed `Client` role authenticates against.

The studio also builds a catalog of furniture, fixtures, and equipment. Each `FFEItem` is added with a `sku`, a `name`, a `category`, a `list_unit_cost_cents`, and a `lead_time_days`, plus an optional `active` flag. The `sku` must be unique across the catalog, and a duplicate is rejected with `ERR_DUPLICATE`. The `category` is one of `FURNITURE`, `LIGHTING`, `TEXTILE`, `DECOR`, or `FIXTURE`. The list unit cost must be greater than zero and the lead time must be at least zero. The `active` flag governs selectability and defaults to true when omitted; an inactive item — one whose `active` is false — cannot be chosen for a new selection, as described in §3.4. Catalog items may be added by either a studio administrator or a designer.

Vendors and trades that fulfill orders are registered with a `name` and a `trade` — one of `SUPPLIER`, `UPHOLSTERY`, `MILLWORK`, `ELECTRICAL`, or `GENERAL` — together with an optional `standing` and an optional `lead_time_buffer_days`. The `standing` defaults to `ACTIVE` and may otherwise be `SUSPENDED`; the buffer, which represents extra days the vendor tacks on top of an item's lead time, defaults to zero and must be at least zero. Vendor registration is open to a procurement coordinator or a studio administrator. A studio administrator may later suspend a vendor, moving its `standing` to `SUSPENDED` and bumping the vendor's version; a suspended vendor cannot receive newly placed orders, as enforced at placement time.

### 3.2. Standing Up a Project from the Brief

A studio administrator turns a client brief into a `Project`. Creation captures the `client_name` shown on the brief, the `client_user_id` naming the `Client` who owns and funds the engagement, a `brief_summary`, the `budget_cents` (the total approved budget, which must be strictly greater than zero), and the `fee_model` that fixes how the studio will bill. The fee model is one of `FLAT`, `HOURLY`, or `MARKUP`, and it is accompanied by exactly the fee field its model requires: `flat_fee_cents`, `hourly_rate_cents`, or `markup_pct`.

The fee fields must be internally consistent with the chosen model, and inconsistency is its own failure. When `fee_model` is `FLAT`, `flat_fee_cents` must be present and greater than zero while both `hourly_rate_cents` and `markup_pct` must be zero. When `fee_model` is `HOURLY`, `hourly_rate_cents` must be present and greater than zero while `flat_fee_cents` and `markup_pct` must be zero. When `fee_model` is `MARKUP`, `markup_pct` must be present and strictly greater than zero and strictly less than one while `flat_fee_cents` and `hourly_rate_cents` must be zero. Any of these fee fields defaults to zero when omitted. A fee-field set that does not satisfy the rule for its model is rejected with `ERR_FEE_MODEL_FIELDS` (HTTP 422); this is distinct from a generic malformed-body rejection and fires specifically on fee-field inconsistency.

A freshly created project enters status `BRIEFING`. Its ledger is then derived from the starting point exactly as it would be after any later recomputation (§2.8): `committed_cents` and `client_credit_cents` start at zero because no orders or deposits exist yet, but `design_fee_cents` is set to the project's provisional design fee per §3.9 — which under the `FLAT` model is `flat_fee_cents` and under the `HOURLY` or `MARKUP` model is zero at this point — and `budget_remaining_cents`, `budget_status`, and `posture` are derived from that starting ledger per §3.8 and §2.8 (so a newly created project is normally `OPEN`). The project's overall `status` walks the lifecycle `BRIEFING → IN_DESIGN → PROCUREMENT → INSTALLATION → CLOSED`, with `ON_HOLD` as a parallel parking state.

Advancing the project forward is a single capability that carries a `to` field naming the target status. Moving from `BRIEFING` to `IN_DESIGN` is performed by a designer and requires that at least one room already exist for the project. Moving from `IN_DESIGN` to `PROCUREMENT`, also driven by a designer, requires two conditions: every room must be `APPROVED` (no room may remain in `SCOPING`, `MOODBOARD_READY`, or `REWORK`, otherwise the advance is rejected with `ERR_ROOMS_NOT_APPROVED`), and no revision request may be in `SUBMITTED` or `CHANGES_REQUESTED` status (otherwise the advance is rejected with `ERR_OPEN_REVISION`). Moving from `PROCUREMENT` to `INSTALLATION` is driven by a procurement coordinator and requires that at least one procurement order be in `IN_TRANSIT` or `DELIVERED` status, failing which the advance is rejected with `ERR_NO_ORDERS_IN_FLIGHT`. Each successful advance sets the new status and increments the project's `version`. An advance whose `to` does not correspond to a legal next step from the current status is an illegal transition and is rejected with `ERR_INVALID_STATE`.

A studio administrator may park a project by putting it `ON_HOLD` from `BRIEFING`, `IN_DESIGN`, or `PROCUREMENT`; holding has no preconditions and simply sets the status to `ON_HOLD` and bumps the version. Resuming a held project is also a studio-administrator action and always returns the project to `IN_DESIGN` regardless of which status it occupied before the hold, again incrementing the version.

Closing the project is the terminal step, reserved for a studio administrator and legal only from `INSTALLATION`. Two preconditions guard it. First, the posture must not be `FROZEN`; since a `FROZEN` posture caused by an open blocking punch item or a `RED` budget would block close, the rejection is `ERR_PROJECT_FROZEN`. Second, every procurement order must already be in a state acceptable for close — that is, in `CLOSED`, `CANCELLED`, `RETURNED`, or `DELIVERED` — and if any order sits outside that set the close is rejected with `ERR_ORDERS_OPEN`. On a successful close, the project's status becomes `CLOSED`, the design fee is finalized and written into `design_fee_cents` (using the final-fee computation of §3.9), the budget tier is recomputed against that finalized fee, and the version increments.

### 3.3. Rooms and Mood Boards: Shaping the Creative Deliverable

Within a project, a designer carves out the work room by room. Each `Room` is created with a `name`, a `scope_note`, and a `room_budget_cents`. The room name must be unique within its project, compared case-sensitively, and a clash is rejected with `ERR_DUPLICATE`; the room budget slice must be at least zero. Every room records the `project_id` of its owning project and begins in status `SCOPING`. A room also carries `approved_moodboard_id`, which stays null until the room is approved and then pins the mood board that was accepted at approval.

A designer creates one or more mood boards for a room, each with a `title` and a `palette` (a list of color or material tokens). A `MoodBoard` records the `room_id` of its owning room and begins in status `DRAFT`. The board lifecycle is `DRAFT → PRESENTED → ACCEPTED`, with `SUPERSEDED` as the alternative terminal outcome. A designer presents a draft board, moving it to `PRESENTED` and bumping its version, but only when no other board for the same room is already presented; if another board for the room is already in `PRESENTED`, the request is rejected with `ERR_MOODBOARD_ALREADY_PRESENTED`.

The room itself advances on the strength of its boards. A designer marks a room `MOODBOARD_READY` from `SCOPING` only when at least one mood board for the room is in `PRESENTED`; absent any presented board, the transition is rejected with `ERR_NO_PRESENTED_MOODBOARD`. From `MOODBOARD_READY`, the client takes one of two actions. The client may approve the room, which is legal only when exactly one mood board for the room is in `PRESENTED` (otherwise `ERR_NO_PRESENTED_MOODBOARD`); approval moves the room to `APPROVED`, transitions that single presented board to `ACCEPTED`, supersedes every other board for the room that was in `DRAFT` or `PRESENTED` (moving each to `SUPERSEDED`), sets `approved_moodboard_id` to the id of the newly accepted board, and increments the room's version. Alternatively, the client may request rework on a `MOODBOARD_READY` room; this needs no precondition, moves the room to `REWORK`, supersedes the presented board (moving it to `SUPERSEDED`), and bumps the room's version. A designer reopens a `REWORK` room back to `SCOPING` with no precondition, again incrementing the version, so the cycle of scoping and presentation can begin afresh.

An approved room is not necessarily approved forever. As §3.7 describes, when a room-targeted revision is resolved against an already-approved room, the system itself drives that room from `APPROVED` back to `REWORK` as a compensation hop: the room's `approved_moodboard_id` is cleared to null, the board that had been accepted is moved to `SUPERSEDED`, and the room's version increments. Note also the system-driven board transitions that ride along with room approval: the single presented board is accepted, and sibling boards still in `DRAFT` or `PRESENTED` at that moment are superseded — each such system transition bumps the affected board's version.

### 3.4. Selecting and Specifying FF&E

With rooms taking shape, a designer selects catalog items to furnish them. Creating a `DesignSelection` names the `room_id` it furnishes (which must belong to the project named in the path), the `ffe_item_id` chosen from the catalog, and a `quantity` of at least one, plus an optional per-line `trade_discount_pct` and an optional `spec_note`. The selection records the `project_id` of its owning project. The referenced catalog item must be active; selecting an item whose `active` is false is rejected with `ERR_FFE_ITEM_INACTIVE`. The trade discount is a fraction that, when supplied, must be at least zero and at most one half; it defaults to zero. The spec note defaults to an empty string.

At creation, the selection pins the catalog price: `unit_cost_cents` is snapshotted from the chosen item's `list_unit_cost_cents` at that moment, so later catalog edits never disturb a selection already made. The system then computes the line's net cost into `line_net_cents`. That line net is the snapshotted unit cost multiplied by the quantity, multiplied by one minus the trade discount fraction, with the product rounded to whole cents using round-half-up. The rounding happens exactly once, at the line level — this is the per-line rounding that order subtotals later sum, and the round point matters because §3.6 builds subtotals by summing already-rounded lines rather than by summing exact products and rounding once at the end. A selection begins in status `PROPOSED`. If a designer edits the trade discount before the selection is specified, the line net is recomputed by the same rule.

Specifying a selection locks its specification, moving it from `PROPOSED` to `SPECIFIED`. Two preconditions apply: the selection's room must be `APPROVED` (otherwise `ERR_ROOM_NOT_APPROVED`), and the `spec_note` must be non-empty (otherwise `ERR_SPEC_NOTE_REQUIRED`). A successful specify increments the selection's version. A designer may withdraw a selection that is in `PROPOSED` with no precondition, moving it to `WITHDRAWN`. A designer may also withdraw a `SPECIFIED` selection, but only if it is not attached to any non-cancelled procurement order; if it is so attached, the withdrawal is rejected with `ERR_SELECTION_ON_ORDER`. Either withdrawal moves the selection to `WITHDRAWN` and bumps its version. A selection reaches `ORDERED` only as a side effect of its order being placed, never by a direct request.

### 3.5. Building and Placing Procurement Orders

A procurement coordinator opens a `ProcurementOrder` against a vendor by supplying the `vendor_id` and the requested delivery window — `window_start` and `window_end`, both ISO 8601 UTC instants, with `window_end` required to be strictly later than `window_start`. The order records the `project_id` of its owning project, begins in status `DRAFT`, and starts with an `order_subtotal_cents` of zero. The order lifecycle is `DRAFT → ORDERED → IN_TRANSIT → DELIVERED → CLOSED`, with a cancel branch reachable from `ORDERED` or `IN_TRANSIT` and a return branch reachable from `DELIVERED`.

A coordinator stocks a draft order by attaching specified selections to it. Attaching creates an `OrderLine` that records the `order_id` of its owning order and the `selection_id` placed onto it, and snapshots that selection's current `line_net_cents` into `line_net_cents_snapshot` so that subsequent edits never disturb a line already committed to an order. Several rules guard the attach. The selection must be in `SPECIFIED` status, and its room must belong to the order's project; a selection may be attached to at most one non-cancelled order. A violation of any of these — a selection already on a non-cancelled order, a selection not yet specified, or a room/project mismatch — is rejected with `ERR_SELECTION_ALREADY_ORDERED`. Each successful attach recomputes the order's `order_subtotal_cents` as the sum, over the order's order lines, of each line's `line_net_cents_snapshot`.

Placing the order is the pivotal commitment, performed by a procurement coordinator and legal only from `DRAFT`. Because placing writes to the shared budget ledger, the request must carry `expected_project_version` matching the project's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) per §2.10. Beyond the version guard, placement runs a battery of business checks. The order must hold at least one order line, or it is rejected as `ERR_ORDER_EMPTY`. The order's vendor must be in `ACTIVE` standing, or placement is rejected with `ERR_VENDOR_SUSPENDED`. The project's posture must permit a new order: a `FROZEN` posture blocks placement with `ERR_PROJECT_FROZEN`, and a `BUDGET_REVIEW` posture blocks placement with `ERR_BUDGET_GATE`. Finally, the requested window must not overlap another non-terminal order on the same vendor; windows are treated as half-open intervals from `window_start` up to but not including `window_end`, so two orders whose windows merely touch at an endpoint do not conflict, but any genuine overlap is rejected with `ERR_VENDOR_WINDOW_CONFLICT`.

These placement guards are evaluated in a definite order. The optimistic-concurrency version match is checked first, so a stale caller is turned away with `ERR_STALE_VERSION` before any business state is consulted. The posture gate is checked next: a `FROZEN` posture surfaces as `ERR_PROJECT_FROZEN` and an `AMBER`-driven `BUDGET_REVIEW` posture surfaces as `ERR_BUDGET_GATE`, ahead of the vendor, window, and emptiness checks, so that a project-level freeze or budget hold is reported rather than being masked by a vendor or line-level problem. Vendor standing (`ERR_VENDOR_SUSPENDED`), window overlap (`ERR_VENDOR_WINDOW_CONFLICT`), and the at-least-one-line requirement (`ERR_ORDER_EMPTY`) follow.

A successful placement is a cascade. The order moves to `ORDERED`; every selection attached to the order moves from `SPECIFIED` to `ORDERED`; the order's `expected_delivery_at` is computed from lead times as described in §3.6; the project's `committed_cents` is recomputed, and from it the project's `budget_status` and `posture` are re-derived; and the project's `version` increments. Because placement is what bumps the project version, two placements cannot both succeed against the same observed version — the second will find its `expected_project_version` stale.

### 3.6. Order Totals, Committed Spend, and Expected Delivery

An order's subtotal is built by the round-then-sum rule, and the order of operations is deliberate. Each selection line is rounded to whole cents first, when its `line_net_cents` is computed in §3.4; the order subtotal is then the exact integer sum of those already-rounded snapshots across the order's lines. The system does not sum the exact fractional products and round once at the end. The two approaches can differ by a cent whenever a trade discount produces a fractional sub-cent on a line, and the contract pins the per-line-round-first behavior.

The project's `committed_cents` is the sum of `order_subtotal_cents` over every procurement order of the project whose status is `ORDERED`, `IN_TRANSIT`, or `DELIVERED`. Orders in `DRAFT`, `CLOSED`, `CANCELLED`, or `RETURNED` contribute nothing to committed spend. From committed spend and the design fee, the project derives `budget_remaining_cents` as the budget less committed spend less the design fee, and it derives a `budget_status` tier as described in §3.8.

When an order is placed, the system fixes its `expected_delivery_at`. For each order line, the system takes the line's selection, looks up that selection's catalog item's `lead_time_days`, and adds the order's vendor's `lead_time_buffer_days`. The order's lead time is the maximum of those per-line sums across all lines. The expected delivery instant is the moment at which the order entered `ORDERED`, advanced forward by that many whole days.

### 3.7. Revisions and Approvals: The Resubmission Cycle

The client raises a `RevisionRequest` against a project to ask for changes to a creative artifact. The request names the `target_kind` — either `ROOM` or `SELECTION` — and the `target_id` of the artifact under revision (a room's id when the kind is `ROOM`, a selection's id when the kind is `SELECTION`), along with a `note` describing what the client wants. The request records the `project_id` of its owning project, starts in status `DRAFT`, and starts with a `round_no` of one. Its lifecycle runs `DRAFT → SUBMITTED → CHANGES_REQUESTED → SUBMITTED` as a cycle, settling finally in either `RESOLVED` or `DISMISSED`.

The client submits a draft request, moving it to `SUBMITTED`, which is permitted only while the project's status is `IN_DESIGN` or `PROCUREMENT` (otherwise `ERR_INVALID_STATE`); submission recomputes the project's posture, since an open revision pushes the posture toward `BUDGET_REVIEW`, and increments the request's version. A designer may then send the request back by requesting changes, moving it from `SUBMITTED` to `CHANGES_REQUESTED` and bumping its version. The client resubmits a `CHANGES_REQUESTED` request — again only while the project is `IN_DESIGN` or `PROCUREMENT`, otherwise `ERR_INVALID_STATE` — which returns it to `SUBMITTED`, increments the round counter `round_no` by one to track the cycle, and increments the version.

A designer closes out a `SUBMITTED` request in one of two ways. Resolving it moves it to `RESOLVED`; if the request targeted a room (`target_kind` is `ROOM`) and that target room is currently `APPROVED`, resolving triggers the compensation hop described in §3.3 — the room reverts from `APPROVED` to `REWORK`, which itself cascades the accepted board to `SUPERSEDED` and clears `approved_moodboard_id` — and in all cases the project's posture is recomputed and the request's version increments. Dismissing the request instead moves it to `DISMISSED`, recomputes the project's posture, and increments the version. Both terminal moves clear the open-revision condition that had been holding the posture in `BUDGET_REVIEW`, so a project with no other gating condition returns to `OPEN`.

### 3.8. Budget Health and the Freezing of Work

A project's `budget_status` is a tier derived from how much of the budget has been spoken for. Utilization is the ratio of committed spend plus the design fee to the total budget — that is, `committed_cents` plus `design_fee_cents`, all divided by `budget_cents`. While the project is open the design-fee component of this ratio uses the provisional fee figure; once the project closes it uses the finalized fee, as detailed in §3.9. The status is `GREEN` when utilization is at most eighty percent; it is `AMBER` when utilization is greater than eighty percent but at most one hundred percent; and it is `RED` when utilization exceeds one hundred percent. The tier boundaries belong to the lower band: a utilization of exactly eighty percent is `GREEN`, and a utilization of exactly one hundred percent is `AMBER`. The comparison is performed on the exact ratio without pre-rounding, so a value a hair above a boundary lands in the higher tier and a value exactly on a boundary lands in the lower one.

This tier feeds directly into posture and thereby into the operational gates of §2.8. An `AMBER` status drives the posture to `BUDGET_REVIEW`, which blocks the placement of new orders with `ERR_BUDGET_GATE`. A `RED` status drives the posture to `FROZEN`, which — alongside the open-blocking-punch-item condition — blocks new orders, blocks advancing into installation, and blocks closing the project, each surfacing as `ERR_PROJECT_FROZEN`. Recomputing `budget_status` is part of every event that changes committed spend, the design fee, or the budget, and the project's `budget_remaining_cents` (the budget less committed spend less the design fee) is recomputed alongside it.

### 3.9. The Design Fee: Provisional While Open, Final at Close

How the studio's `design_fee_cents` is computed depends entirely on the project's `fee_model`, and for two of the three models the figure shown while the project is open (the provisional fee) differs from the figure pinned at close (the final fee).

Under the `FLAT` model the fee is simply `flat_fee_cents`, and the provisional and final figures are identical.

Under the `HOURLY` model the fee is built from approved billable time. The system gathers the qualifying time entries, converts each to billable hours, sums them into billable hours, and multiplies that total by `hourly_rate_cents`, rounding the product to whole cents once at the end with round-half-up. The per-entry conversion bills time in quarter-hour increments, always rounding up: an entry's minutes are divided by fifteen, rounded up to the next whole increment, and each increment counts as a quarter of an hour. So an entry of one to fifteen minutes counts as a quarter hour, sixteen to thirty minutes as half an hour, and so on. The final fee counts only time entries whose status is `APPROVED` and whose `billable` flag is true. The provisional fee, shown while the project's status is anything other than `CLOSED`, is more inclusive: it counts time entries that are billable and in either `SUBMITTED` or `APPROVED` status, so not-yet-approved hours are reflected in the running estimate.

Under the `MARKUP` model the fee is `markup_pct` multiplied by a committed base, with the product rounded to whole cents once at the end using round-half-up. For the final fee, the committed base is the sum of `order_subtotal_cents` over the project's procurement orders whose status is `ORDERED`, `IN_TRANSIT`, or `DELIVERED`. The provisional fee uses a broader base: it adds to that set the subtotals of orders still in `DRAFT`, so the committed base for the provisional markup fee covers orders in `DRAFT`, `ORDERED`, `IN_TRANSIT`, or `DELIVERED`.

Designers log work against a project by submitting a `TimeEntry` that carries the `designer_user_id` of the operator who did the work, the `minutes` worked (at least one), and an optional `billable` flag that defaults to true. A time entry starts in status `SUBMITTED`. A studio administrator approves a submitted entry, but only when the project's `fee_model` is `HOURLY`; approving against any other fee model is rejected with `ERR_FEE_MODEL_MISMATCH`. A successful approval moves the entry to `APPROVED`, recomputes the project's design fee (both its provisional and final figures) and consequently its budget tier and posture, and increments the entry's version. A studio administrator may instead reject a submitted entry with no precondition, moving it to `REJECTED` and bumping its version.

A read-only fee-quote capability returns both the provisional and final design-fee figures together with a budget snapshot, computed by the same rules without mutating anything. The response body exposes the provisional and final fees as two distinct fields named `provisional_design_fee_cents` and `final_design_fee_cents` (it does not expose a single `design_fee_cents` field), alongside the budget snapshot fields `committed_cents`, `budget_cents`, `budget_remaining_cents`, `budget_status`, and `client_credit_cents`. The snapshot's `budget_remaining_cents` and `budget_status` are computed using the provisional fee while the project is open and the final fee once it is `CLOSED`, consistent with §3.8.

### 3.10. Deposits and the Allocation Waterfall

The client funds the project through deposits, recorded by a studio administrator as a `PaymentReceipt` carrying the `amount_cents` deposited (which must be greater than zero), the `received_at` instant the money arrived, and an optional `memo`. The receipt records the `project_id` of the project it credits. Because recording a deposit re-allocates money across the project's outstanding orders, the request must carry `expected_project_version` matching the project's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), as §2.10 explains.

Recording a deposit — and, as §3.11 notes, cancelling or returning an order — runs the deposit waterfall, which allocates the full pool of money the client has ever deposited across the orders that currently owe money. The pool is the sum of `amount_cents` over every payment receipt for the project. The outstanding orders are those in `ORDERED`, `IN_TRANSIT`, or `DELIVERED` status, sorted by their `created_at` timestamp ascending, with the earlier-created order always taking precedence. The system walks that sorted list and fills each order's balance fully before moving to the next: for each order in turn, it allocates the smaller of the remaining pool and the order's `order_subtotal_cents`, records that allocated amount as the order's `amount_paid_cents`, sets the order's `balance_due_cents` to its subtotal less the amount paid, and reduces the remaining pool by the amount allocated. Whatever pool remains after every outstanding order is filled becomes the project's `client_credit_cents`, the unallocated remainder. Any order not in the outstanding set has an `amount_paid_cents` of zero. There is no fractional splitting: each order is filled completely before the next receives anything.

### 3.11. Shipping, Delivery, Cancellation, and Returns

Once placed, an order is shepherded by a procurement coordinator through fulfillment. Shipping moves an order from `ORDERED` to `IN_TRANSIT` and bumps the order's version. Delivering moves it from `IN_TRANSIT` to `DELIVERED` and bumps its version. Closing the order moves it from `DELIVERED` to `CLOSED` and bumps its version, but only when no punch item on the order remains in `OPEN`; an attempt to close over open punch items is rejected with `ERR_PUNCH_ITEMS_OPEN`.

Two divergent branches handle trouble. A coordinator may cancel an order that is in `ORDERED` or `IN_TRANSIT`, with no precondition. Cancelling moves the order to `CANCELLED` and runs a compensation cascade: every selection attached to the order reverts from `ORDERED` back to `SPECIFIED`; the project's `committed_cents` is recomputed (the order having left the committed set) and from it the `budget_status` and `posture` are re-derived; any deposit money previously allocated to this order is released back into the project's `client_credit_cents` by re-running the deposit waterfall over the new outstanding set; and the project's `version` increments.

A coordinator may return an order only from `DELIVERED`, and only when the order carries at least one punch item of severity `BLOCKING`; a return without such justification is rejected with `ERR_RETURN_NOT_JUSTIFIED`. Returning moves the order to `RETURNED` and runs a comparable compensation cascade: every attached selection reverts from `ORDERED` back to `SPECIFIED`; every punch item still `OPEN` on the order is moved to `WAIVED`; the project's `committed_cents`, `budget_status`, and `posture` are recomputed; the deposit is re-allocated through the waterfall; and the project's `version` increments. Both `CANCELLED` and `RETURNED` are terminal for the order.

### 3.12. The Punch List and Install Close-Out

During and after install, defects are tracked as punch items. A procurement coordinator or a designer logs a `PunchListItem` against a delivered order, supplying a `description` and a `severity` — one of `MINOR`, `MAJOR`, or `BLOCKING`. The item records the `order_id` of the order the defect was found against and begins in status `OPEN`. Logging an item recomputes the project's posture, and because a `BLOCKING` item that is `OPEN` is the highest-priority freeze condition, logging a blocking defect drives the project to `FROZEN`.

Punch items are cleared in one of two ways. A procurement coordinator resolves an item, moving it from `OPEN` to `RESOLVED`; the resolution recomputes the project's posture, and clearing the last open blocking item may be what lifts a `FROZEN` posture. A client waives an item, moving it from `OPEN` to `WAIVED`; this too recomputes the posture. Each move increments the punch item's version. The interplay with project close is direct: because a project cannot close while frozen, and an open blocking punch item freezes the project, every blocking defect must be resolved or waived (and, separately, every order brought to a close-eligible state) before the studio administrator can move the project to `CLOSED`.

## 4. Endpoint Definitions

The API is mounted at the root path. Operations that create a brand-new resource return `201 Created`. Operations that modify an existing resource — including every state-transition action and every read — return `200 OK`. The table below is a routing summary only; the request payloads, response shapes, and side effects of each endpoint are defined in the §3 narratives above and must be reconstructed from them.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/clients` | Register a Client account | StudioAdmin |
| GET | `/clients/{id}` | Get a Client | StudioAdmin, Client |
| POST | `/projects` | Create a Project from the client brief | StudioAdmin |
| GET | `/projects/{id}` | Get a Project including derived ledger fields and posture | StudioAdmin, Designer, ProcurementCoordinator, Client |
| GET | `/projects` | List projects (filter by `client_user_id`) | StudioAdmin, Designer, ProcurementCoordinator, Client |
| POST | `/projects/{project_id}/advance` | Advance project status forward | Designer, ProcurementCoordinator |
| POST | `/projects/{project_id}/hold` | Put project ON_HOLD | StudioAdmin |
| POST | `/projects/{project_id}/resume` | Resume an ON_HOLD project to IN_DESIGN | StudioAdmin |
| POST | `/projects/{project_id}/close` | Close the project and finalize the design fee | StudioAdmin |
| GET | `/projects/{project_id}/fee-quote` | Computed read: provisional and final design fee plus budget snapshot | StudioAdmin, Designer, Client |
| POST | `/projects/{project_id}/payments` | Record a client deposit (OCC on Project.version) | StudioAdmin |
| GET | `/payments/{id}` | Get a payment receipt | StudioAdmin, Client |
| GET | `/payments` | List payment receipts (filter by `project_id`) | StudioAdmin, Client |
| POST | `/projects/{project_id}/rooms` | Add a room/scope | Designer |
| GET | `/rooms/{id}` | Get a room | StudioAdmin, Designer, ProcurementCoordinator, Client |
| GET | `/rooms` | List rooms (filter by `project_id` and/or `approved_moodboard_id`) | StudioAdmin, Designer, ProcurementCoordinator, Client |
| POST | `/rooms/{room_id}/present-moodboard` | Mark room MOODBOARD_READY | Designer |
| POST | `/rooms/{room_id}/approve` | Client approves room; pins mood board | Client |
| POST | `/rooms/{room_id}/request-rework` | Client sends room back to REWORK | Client |
| POST | `/rooms/{room_id}/reopen-scope` | Designer reopens a REWORK room to SCOPING | Designer |
| POST | `/rooms/{room_id}/moodboards` | Create a mood board for a room | Designer |
| GET | `/moodboards/{id}` | Get a mood board | StudioAdmin, Designer, Client |
| GET | `/moodboards` | List mood boards (filter by `room_id`) | StudioAdmin, Designer, Client |
| POST | `/moodboards/{moodboard_id}/present` | Present a DRAFT mood board | Designer |
| POST | `/ffe-items` | Add a catalog FF&E item | StudioAdmin, Designer |
| GET | `/ffe-items/{id}` | Get a catalog item | StudioAdmin, Designer, ProcurementCoordinator |
| POST | `/projects/{project_id}/selections` | Select an FF&E item for a room | Designer |
| GET | `/selections/{id}` | Get a selection | StudioAdmin, Designer, ProcurementCoordinator, Client |
| GET | `/selections` | List selections (filter by `project_id`/`room_id`/`ffe_item_id`) | StudioAdmin, Designer, ProcurementCoordinator, Client |
| POST | `/selections/{selection_id}/specify` | Lock spec on a selection (PROPOSED to SPECIFIED) | Designer |
| POST | `/selections/{selection_id}/withdraw` | Withdraw a selection | Designer |
| POST | `/vendors` | Register a vendor/trade | ProcurementCoordinator, StudioAdmin |
| GET | `/vendors/{id}` | Get a vendor | StudioAdmin, ProcurementCoordinator |
| POST | `/vendors/{vendor_id}/suspend` | Suspend a vendor (standing to SUSPENDED) | StudioAdmin |
| POST | `/projects/{project_id}/orders` | Open a DRAFT procurement order for a vendor | ProcurementCoordinator |
| GET | `/orders/{id}` | Get an order including computed totals | StudioAdmin, ProcurementCoordinator, Designer, Client |
| GET | `/orders` | List orders (filter by `project_id`/`vendor_id`) | StudioAdmin, ProcurementCoordinator, Designer, Client |
| POST | `/orders/{order_id}/lines` | Attach a SPECIFIED selection to a DRAFT order | ProcurementCoordinator |
| GET | `/order-lines/{id}` | Get an order line | StudioAdmin, ProcurementCoordinator, Designer |
| GET | `/order-lines` | List order lines (filter by `order_id`/`selection_id`) | StudioAdmin, ProcurementCoordinator, Designer |
| POST | `/orders/{order_id}/place` | Place a DRAFT order (OCC on Project.version) | ProcurementCoordinator |
| POST | `/orders/{order_id}/ship` | ORDERED to IN_TRANSIT | ProcurementCoordinator |
| POST | `/orders/{order_id}/deliver` | IN_TRANSIT to DELIVERED | ProcurementCoordinator |
| POST | `/orders/{order_id}/close-order` | DELIVERED to CLOSED (no open punch items) | ProcurementCoordinator |
| POST | `/orders/{order_id}/cancel` | Cancel an ORDERED/IN_TRANSIT order (compensation) | ProcurementCoordinator |
| POST | `/orders/{order_id}/return-order` | Return a DELIVERED order with a BLOCKING punch item | ProcurementCoordinator |
| POST | `/projects/{project_id}/revisions` | Open a revision/approval request | Client |
| GET | `/revisions/{id}` | Get a revision | StudioAdmin, Designer, Client |
| GET | `/revisions` | List revisions (filter by `project_id`/`target_id`) | StudioAdmin, Designer, Client |
| POST | `/revisions/{revision_id}/submit` | Submit (or resubmit) a revision | Client |
| POST | `/revisions/{revision_id}/request-changes` | Designer requests changes (cycle) | Designer |
| POST | `/revisions/{revision_id}/resolve` | Designer resolves a revision | Designer |
| POST | `/revisions/{revision_id}/dismiss` | Designer dismisses a revision | Designer |
| POST | `/orders/{order_id}/punch-items` | Log an install defect on a DELIVERED order | ProcurementCoordinator, Designer |
| GET | `/punch-items/{id}` | Get a punch item | StudioAdmin, ProcurementCoordinator, Designer, Client |
| GET | `/punch-items` | List punch items (filter by `order_id`) | StudioAdmin, ProcurementCoordinator, Designer, Client |
| POST | `/punch-items/{punch_item_id}/resolve` | Resolve a punch item | ProcurementCoordinator |
| POST | `/punch-items/{punch_item_id}/waive` | Client waives a punch item | Client |
| POST | `/projects/{project_id}/time-entries` | Log designer time against a project | Designer |
| GET | `/time-entries/{id}` | Get a time entry | StudioAdmin, Designer |
| GET | `/time-entries` | List time entries (filter by `project_id`) | StudioAdmin, Designer |
| POST | `/time-entries/{time_entry_id}/approve` | Approve a time entry (feeds HOURLY fee) | StudioAdmin |
| POST | `/time-entries/{time_entry_id}/reject` | Reject a time entry | StudioAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 422 Unprocessable Entity |
| `ERR_FEE_MODEL_FIELDS` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_PROJECT_FROZEN` | 409 Conflict |
| `ERR_BUDGET_GATE` | 409 Conflict |
| `ERR_VENDOR_SUSPENDED` | 409 Conflict |
| `ERR_VENDOR_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_ORDER_EMPTY` | 409 Conflict |
| `ERR_SELECTION_ALREADY_ORDERED` | 409 Conflict |
| `ERR_SELECTION_ON_ORDER` | 409 Conflict |
| `ERR_FFE_ITEM_INACTIVE` | 409 Conflict |
| `ERR_ROOM_NOT_APPROVED` | 409 Conflict |
| `ERR_ROOMS_NOT_APPROVED` | 409 Conflict |
| `ERR_OPEN_REVISION` | 409 Conflict |
| `ERR_NO_ORDERS_IN_FLIGHT` | 409 Conflict |
| `ERR_ORDERS_OPEN` | 409 Conflict |
| `ERR_NO_PRESENTED_MOODBOARD` | 409 Conflict |
| `ERR_MOODBOARD_ALREADY_PRESENTED` | 409 Conflict |
| `ERR_SPEC_NOTE_REQUIRED` | 409 Conflict |
| `ERR_PUNCH_ITEMS_OPEN` | 409 Conflict |
| `ERR_RETURN_NOT_JUSTIFIED` | 409 Conflict |
| `ERR_FEE_MODEL_MISMATCH` | 409 Conflict |
| `ERR_DUPLICATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_VALIDATION` | 400 Bad Request |
