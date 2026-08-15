# Bonded Warehouse FTZ API — Product Requirements Document

## 1. Introduction

Foreign-trade zones allow importers to admit merchandise under bond, defer customs duty while goods remain inside the zone, extinguish that duty entirely when goods are exported, and pay only when goods formally enter domestic commerce. Running such a zone is an audit-driven business: every unit of merchandise must be attributed to a duty status, every dollar of deferred exposure must stay inside the operator's surety bond, and once a year the operator must reconcile its book inventory against a physical count under the eye of U.S. Customs and Border Protection. This document specifies an API for a zone operator platform that manages that full lifecycle — admission and entry documentation, duty deferral and inventory attribution by zone status, in-zone manipulation and assembly with the resulting change in dutiable value, withdrawals for consumption or export, weekly consolidated entries and the merchandise processing fee savings they produce, annual reconciliation and CBP reporting, and gate-level security and access control.

The platform serves four distinct operator populations. Zone operator staff run the facility, approve manipulation work, file annual reconciliations, and issue access badges. Importers of record file admission documentation, request manipulation orders, and create and file withdrawals and weekly entries for the merchandise they own. CBP officers admit merchandise, return deficient documentation, confirm exports, and adjudicate weekly entries and annual reconciliations. Gate security officers record personnel entry and exit. Because the zone's records are the legal basis of duty deferral, every mutation and every cascade it triggers must be visible immediately in the same request's response and in all subsequent reads — there is no eventual consistency anywhere in this system.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, wire contracts, and cross-cutting disciplines that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

All interactions with the API are authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which declares the capacity in which that user acts. The system recognizes exactly four roles: `ZoneOperator`, `Importer`, `CustomsOfficer`, and `GateOfficer`. A request missing either header, or carrying a role value outside these four declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not listed among the roles authorized for the target endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403).

For each of the four roles — `ZoneOperator`, `Importer`, `CustomsOfficer`, and `GateOfficer` — `X-User-ID` is an opaque operator identifier that is never compared to the `id` of any persisted entity. When `X-User-Role` is `Importer`, the server records the supplied `X-User-ID` as the `importer_ref` of every admission, manipulation order, withdrawal, and weekly entry that importer creates, and ownership checks on those resources compare the resource's `importer_ref` against the caller's `X-User-ID`. When `X-User-Role` is `ZoneOperator`, `CustomsOfficer`, or `GateOfficer`, the identifier establishes authority to act only; it is not recorded as an ownership anchor on any resource.

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

Endpoints that return lists of resources accept two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by creation timestamp in ascending order.

Paginated list responses carry four fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the system — zones, admissions, inventory lots, manipulation orders, withdrawals, weekly entries, annual reconciliations, and access badges — carries a standard set of system-managed fields:

- `id` (string): a server-minted UUID that serves purely as the resource's identity; it carries no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the resource's last modification; it refreshes on every change to the resource's properties.
- `version` (integer): a system-managed integer that increments by one on every modification of the resource, including server-side cascades that rewrite derived fields on it.

The zone access event log is the deliberate exception. A `ZoneAccessEvent` is an append-only audit record carrying only `id` and `created_at` alongside its event payload; `updated_at` and `version` are absent, and the record is immutable once written.

### 2.5. The Logical Clock

All timestamps the system stamps on its own behalf — an admission's `admission_date`, a withdrawal's `withdrawal_date`, and the default `occurred_at` of a gate event — are read from a server-side logical clock, never from wall-clock time. At server startup the logical clock reads exactly 2026-08-01T00:00:00Z; until it is explicitly set, every logical-clock read returns this default, and the clock never falls back to wall-clock time at any point.

A test-driving capability lets any of the four roles advance the logical clock by supplying a `to_iso8601` timestamp; the response body reports the clock's new reading as `current_utc`. Workflows that depend on the passage of time — entry-week membership windows, badge validity windows, reconciliation year windows — all evaluate against this logical clock.

### 2.6. Money, Duty Rates, and Rounding Discipline

All monetary amounts in the system are represented as integer cents: declared values, duty amounts, fee amounts, bond coverage, and reconciliation figures are all whole-cent integers with no fractional component. Duty rates, by contrast, are decimal fractions (an ad valorem rate of 0.05 means five percent of value).

All monetary arithmetic is performed with decimal arithmetic, and all rounding is round half up to integer cents, applied at exactly the steps each calculation in §3 pins down — no earlier, no later. A small number of calculations deliberately round intermediate results before combining them; where a formula pins such an order, reversing it produces different cents and is non-conformant. The single exception to integer-cent output is the reconciliation's `discrepancy_pct`, which is a percentage rounded half up to four decimal places.

### 2.7. Optimistic Concurrency Control

Exactly one endpoint in the API participates in optimistic concurrency control: the creation of an annual reconciliation. Such a request must carry `expected_zone_version` as a non-optional input, holding the `version` of the target zone the client last observed. If the zone's current `version` does not equal the supplied `expected_zone_version`, the create is rejected with `ERR_STALE_ZONE_VERSION` (HTTP 412), because the client would otherwise be filing against a zone state it has never seen. No other endpoint accepts or honors a version field; clients must not send one elsewhere.

### 2.8. Resource Existence, Path Validation, and Cross-Zone References

The API is organized as a set of peer collections mounted under a common top-level path, with resources joined by foreign-key references in request bodies and query filters rather than by deep URL nesting. When a request path contains resource identifiers — `zoneId`, `admissionId`, `lotId`, `orderId`, `withdrawalId`, `entryId`, `reconId`, `badgeId`, or `eventId` — the server validates their existence strictly left to right and rejects the request at the first identifier that does not resolve. Each unresolved identifier maps to its own error: `ERR_ZONE_NOT_FOUND`, `ERR_ADMISSION_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_MANIPULATION_ORDER_NOT_FOUND`, `ERR_WITHDRAWAL_NOT_FOUND`, `ERR_WEEKLY_ENTRY_NOT_FOUND`, `ERR_RECONCILIATION_NOT_FOUND`, `ERR_BADGE_NOT_FOUND`, or `ERR_ACCESS_EVENT_NOT_FOUND`, all HTTP 404. Once path identifiers resolve, foreign keys carried in the request body — `zone_id`, `lot_id`, `source_lot_id`, `weekly_entry_id`, and `badge_id` — are validated for existence in the same fashion.

Because these collections are peers rather than nested children, the API additionally enforces cross-zone referential consistency: a withdrawal must name the same zone as the lot it draws from, a weekly entry attached to a withdrawal must belong to that same zone, and a gate event must name the same zone as the badge it cites. Any such mismatch is rejected with `ERR_CROSS_ZONE_REFERENCE` (HTTP 422).

### 2.9. Validation Discipline and Error Precedence

Every mutating request passes through a fixed validation cascade, and the first failure encountered wins — a request that violates several rules is rejected with the error belonging to the earliest category, never with a list. The categories, in evaluation order, are:

1. **Caller context.** The `X-User-ID` and `X-User-Role` headers must be present and the role must be one of the four declared roles; otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Endpoint permission.** The caller's role must be listed on the endpoint; otherwise `ERR_INSUFFICIENT_PERMISSIONS`.
3. **Existence.** Path identifiers are validated left to right, then body foreign keys, each failure surfacing the corresponding not-found error of §2.8.
4. **Request schema.** Every required field must be present, every type must be correct, every enum member must be valid, `quantity` values must be at least 1, monetary inputs such as `unit_value_cents`, `value_added_cents`, and `bond_coverage_cents` must be at least 0, and a badge's `valid_from` must be strictly before its `valid_until`. Unknown fields in a body are rejected outright. Any failure here yields `ERR_INVALID_REQUEST` (HTTP 400).
5. **Ownership.** Where a rule ties a resource to its creating importer, the caller's identity must match; otherwise `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
6. **State preconditions.** The target resource must be in a valid from-state for the requested action (the `ERR_*_INVALID_TRANSITION` family and `ERR_LOT_NOT_IN_ZONE`), zone gates of §2.10 must hold where the workflow declares them (`ERR_ZONE_NOT_ACTIVE`, `ERR_ZONE_AUDIT_HOLD`), zone deactivation requires an empty zone (`ERR_ZONE_NOT_EMPTY`), the withdrawal's type must match the action (`ERR_WRONG_WITHDRAWAL_TYPE`), an attached weekly entry must be `OPEN` where declared (`ERR_ENTRY_NOT_OPEN`), and the optimistic-concurrency check of §2.7 must pass (`ERR_STALE_ZONE_VERSION`).
7. **Customs and security prohibitions.** The hard prohibitions of the domain — consumption of zone-restricted merchandise, manipulation of zone-restricted merchandise, and gate access on a non-active badge — yield `ERR_ZR_CONSUMPTION_FORBIDDEN`, `ERR_MANIPULATION_NOT_PERMITTED`, and `ERR_BADGE_ACCESS_DENIED` respectively, all HTTP 422.
8. **Temporal and interval rules.** Window-overlap and sequence rules yield `ERR_WEEK_WINDOW_OVERLAP` (HTTP 409), `ERR_BADGE_WINDOW_OVERLAP` (HTTP 409), `ERR_WITHDRAWAL_OUTSIDE_ENTRY_WEEK` (HTTP 422), `ERR_BADGE_WINDOW_VIOLATION` (HTTP 422), and `ERR_GATE_SEQUENCE_VIOLATION` (HTTP 422).
9. **Resource constraints.** Quantity, reservation, membership, and duplicate-submission constraints yield `ERR_INSUFFICIENT_QUANTITY` (HTTP 422), `ERR_LOT_BUSY` (HTTP 422), `ERR_ENTRY_NO_LINE_ITEMS` (HTTP 422), and `ERR_RECONCILIATION_ALREADY_SUBMITTED` (HTTP 409).
10. **Referential consistency with external tables and zones.** Tariff codes must exist and zone references must align, yielding `ERR_UNKNOWN_HTS_CODE` (HTTP 422) and `ERR_CROSS_ZONE_REFERENCE` (HTTP 422).
11. **Fiscal capacity.** The surety-bond ceiling is enforced last, yielding `ERR_BOND_CAPACITY_EXCEEDED` (HTTP 402).

A consequence worth internalizing: a request that would both breach the bond ceiling and fail body-schema validation is rejected with `ERR_INVALID_REQUEST`, because schema checks run eight categories before fiscal capacity.

### 2.10. Zone Activity and Compliance Gating

Two independent zone-level gates recur throughout the workflows of §3, and both are always evaluated at state-precondition level in the cascade above. The first is the operator-controlled lifecycle: many operations require the zone's `status` to be `ACTIVE`, and reject with `ERR_ZONE_NOT_ACTIVE` (HTTP 409) when it is not. The second is the compliance posture: a narrower set of operations — those that move merchandise or money — additionally require the zone's `compliance_posture` to be `NORMAL`, and reject with `ERR_ZONE_AUDIT_HOLD` (HTTP 409) while the zone sits in `AUDIT_HOLD`. Cancellation paths deliberately check only the first gate, so that an importer can always unwind work even while a zone is suspended or under audit hold; each workflow in §3 states exactly which gates it enforces.

## 3. Business Logic & Workflows

### 3.1. Provisioning a Zone and Its Operator Lifecycle

Everything begins with the **Zone**. A `ZoneOperator` provisions a zone by supplying a human-readable `name`, an operator-assigned `zone_code` (free text carried for information only), and a `bond_coverage_cents` amount — the surety bond that caps the zone's total deferred duty exposure. A new zone starts with `status` set to `ACTIVE`, `compliance_posture` set to `NORMAL`, and both `deferred_duty_exposure_cents` and `active_lot_count` at zero.

The operator controls a simple lifecycle through a transition action carrying a `to_status` value. Suspending moves a zone from `ACTIVE` to `SUSPENDED`; reactivating moves it from `SUSPENDED` back to `ACTIVE`. Deactivation is permanent: from either `ACTIVE` or `SUSPENDED` the zone moves to the terminal `DEACTIVATED` state, but only when the zone holds no live merchandise — deactivation is rejected with `ERR_ZONE_NOT_EMPTY` unless the zone's `active_lot_count` is zero. Any request whose `to_status` is not reachable from the zone's current status is rejected with `ERR_ZONE_INVALID_TRANSITION`. Each successful operator transition increments the zone's `version` by one.

The second zone dimension, `compliance_posture`, is never set by an operator directly. It is driven entirely by the annual reconciliation machinery of §3.7, moving from `NORMAL` to `AUDIT_HOLD` when a filed reconciliation flags a material variance and returning to `NORMAL` when customs accepts a reconciliation. Listing zones and reading a single zone are available to all four roles.

### 3.2. Admission Documentation and Merchandise Intake

An **Admission** is the documentation an `Importer` files to bring merchandise into a zone. The importer creates it as a `DRAFT` by supplying the receiving `zone_id`, a merchandise `description`, the `hts_code` under which the goods are classified, the `quantity` of units (at least 1), the declared `unit_value_cents` per unit (at least 0), and the `zone_status` designation the merchandise will carry: `PRIVILEGED_FOREIGN`, `NON_PRIVILEGED_FOREIGN`, `DOMESTIC`, or `ZONE_RESTRICTED`. The server anchors the admission to its creator by stamping `importer_ref` from the caller's identity. Drafting is deliberately permissive: the tariff code's presence in the schedule is not verified at creation time. Admissions may be listed with optional `zone_id`, `importer_ref`, `status`, and `zone_status` filters, and read individually, by any role.

When the documentation is ready, the owning importer submits it, moving the admission from `DRAFT` to `SUBMITTED`. Submission requires the caller to own the admission (otherwise `ERR_NOT_RESOURCE_OWNER`), requires the admission to currently be `DRAFT` (otherwise `ERR_ADMISSION_INVALID_TRANSITION`), and requires the zone to be `ACTIVE` with posture `NORMAL` (otherwise `ERR_ZONE_NOT_ACTIVE` or `ERR_ZONE_AUDIT_HOLD` respectively).

Customs review is a two-outcome gate operated by a `CustomsOfficer`. If the documentation is deficient, customs returns it, moving the admission from `SUBMITTED` back to `DRAFT`; the submit–return loop may repeat as many times as needed. If the documentation is sound, customs admits the merchandise, moving the admission from `SUBMITTED` to the terminal `ADMITTED` state. Admission enforces four checks beyond the transition itself: the zone must be `ACTIVE` with posture `NORMAL`; the admission's `hts_code` must exist in the tariff schedule at this moment, otherwise `ERR_UNKNOWN_HTS_CODE`; and the zone's bond ceiling must absorb the new merchandise — admitting is rejected with `ERR_BOND_CAPACITY_EXCEEDED` when the zone's current `deferred_duty_exposure_cents` plus the deferred-duty estimate of the lot the admission would create exceeds the zone's `bond_coverage_cents`, with exact equality permitted.

Admitting stamps `admission_date` from the logical clock (the field is null beforehand) and creates an **InventoryLot** in `IN_ZONE` status whose `admitted_quantity` and `quantity_on_hand` both equal the admission's `quantity`, whose `unit_value_cents` and `duty_rate` are resolved per the valuation rules of §3.3, and whose `zone_status`, `hts_code`, and `importer_ref` are copied from the admission. The zone's `deferred_duty_exposure_cents` and `active_lot_count` are then recomputed to reflect the new lot.

An importer may also cancel an admission outright, from either `DRAFT` or `SUBMITTED`, moving it to the terminal `CANCELLED` state. Cancellation requires ownership (`ERR_NOT_RESOURCE_OWNER`) and an `ACTIVE` zone (`ERR_ZONE_NOT_ACTIVE`), but is intentionally not blocked by an audit hold; acting from any other status yields `ERR_ADMISSION_INVALID_TRANSITION`.

### 3.3. Duty Deferral, Lot Valuation, and Bond Exposure

The system's tariff schedule recognizes exactly four Harmonized Tariff Schedule codes and their ad valorem duty rates: `0401.10` at a rate of 0.05, `8542.31` at 0.04, `9503.00` at 0.12, and `8708.29` at 0.025. Every duty calculation in the platform resolves through this table, and any admission or manipulation order citing a code outside it fails at the verification point with `ERR_UNKNOWN_HTS_CODE`.

How a lot's `duty_rate` and dutiable value basis are resolved depends on its `zone_status`. A `DOMESTIC` lot always carries a `duty_rate` of zero. A `PRIVILEGED_FOREIGN` lot keeps the rate and per-unit value basis locked in when its merchandise was admitted — for a lot produced by in-zone manipulation, the locked rate and the components' value basis carry over from the source lot, making privileged merchandise insensitive to value change inside the zone. A `NON_PRIVILEGED_FOREIGN` lot is re-derived as merchandise stands when withdrawn: its `duty_rate` comes from the tariff schedule at the lot's current `hts_code`, and a manipulated output lot's value basis includes the value added in the zone. A `ZONE_RESTRICTED` lot is valued exactly like a non-privileged foreign one — its duty remains deferred — but, as §3.5 explains, it may never be withdrawn for consumption.

A lot is never written directly through the API: lots arise only from admitted admissions and completed manipulation orders, and they change only through withdrawal filings and cancellations, manipulation approvals and completions, and the freeze cascade of §3.7. A newly created lot's `reserved_quantity`, `cumulative_withdrawn`, and `cumulative_consumed` all start at zero.

The zone's deferred exposure is a standing aggregate. The zone's `deferred_duty_exposure_cents` is the sum, taken over every lot of the zone whose status is `IN_ZONE`, of that lot's deferred-duty estimate: the lot's `quantity_on_hand` multiplied by its `unit_value_cents` and by its `duty_rate`, each lot's product rounded half up to integer cents before the products are summed. `DEPLETED` lots contribute nothing and are excluded. The zone's `active_lot_count` is the count of its lots in `IN_ZONE`. These aggregates are recomputed immediately whenever any lot's on-hand quantity changes or its membership in `IN_ZONE` changes — that is, upon an admission being admitted, a withdrawal being filed, a withdrawal cancellation, a manipulation completion, or the freeze cascade of §3.7 — so the exposure a `ZoneOperator` reads is always current, and the `ERR_BOND_CAPACITY_EXCEEDED` check at admission time always evaluates against live figures.

### 3.4. In-Zone Manipulation and Assembly

Importers may transform merchandise inside the zone — assembling, repacking, or manufacturing — through a **ManipulationOrder**. The owning importer requests one by supplying the `zone_id`, the `source_lot_id` whose units will be consumed, the `input_quantity` of source units to consume (at least 1), the `output_hts_code` of the finished good, the `output_quantity` of finished units to be produced (at least 1), the `value_added_cents` the in-zone work adds (at least 0), and an `output_description`. The order starts in `REQUESTED`, stamped with the creator's `importer_ref`; the caller must own the source lot, so a request naming a lot whose `importer_ref` differs from the caller's identity is rejected with `ERR_NOT_RESOURCE_OWNER`. Orders can be listed with optional `zone_id`, `source_lot_id`, `output_lot_id`, and `status` filters.

Approval belongs to the `ZoneOperator` and is the moment the system's guards bite. Approving requires the order to be `REQUESTED` (otherwise `ERR_ORDER_INVALID_TRANSITION`); the zone to be `ACTIVE` with posture `NORMAL`; the source lot to exist and be `IN_ZONE` (otherwise `ERR_LOT_NOT_IN_ZONE`); the source lot's `zone_status` to be anything other than `ZONE_RESTRICTED`, because zone-restricted merchandise may never be manipulated (otherwise `ERR_MANIPULATION_NOT_PERMITTED`); the lot to be free of other commitments — its `reserved_quantity` must be zero, so a lot already reserved under another approved order rejects with `ERR_LOT_BUSY`; the order's `input_quantity` to be at most the lot's `quantity_on_hand` minus its `reserved_quantity` (otherwise `ERR_INSUFFICIENT_QUANTITY`); and the `output_hts_code` to exist in the tariff schedule at approval time (otherwise `ERR_UNKNOWN_HTS_CODE`). On approval the source lot's `reserved_quantity` is increased by the order's `input_quantity`: those units remain physically on hand — `quantity_on_hand` still includes them — but are unavailable to any other withdrawal or order until the work completes.

Completion is performed by the owning importer against an `APPROVED` order, requires the usual ownership, zone-`ACTIVE`, and posture-`NORMAL` gates, and produces three linked effects. First, the source lot is debited: its `quantity_on_hand` is decreased by the `input_quantity`, its `reserved_quantity` is decreased by the same amount, and its `cumulative_consumed` is increased by the same amount. Second, if that debit leaves the source lot with zero on hand it transitions from `IN_ZONE` to `DEPLETED`; simultaneously the output lot is created in `IN_ZONE` with `admitted_quantity` and `quantity_on_hand` both equal to the order's `output_quantity`, its `zone_status` inherited from the source lot, its `source_manipulation_id` set to this order, its `admission_id` null, and its `importer_ref` inherited from the source lot; the order's `output_lot_id` (null until now) points at the new lot, and the order becomes `COMPLETED`. Third, the zone's `active_lot_count` and `deferred_duty_exposure_cents` are recomputed.

The output lot's valuation is pinned precisely. The input share is computed first: the order's `input_quantity` multiplied by the source lot's `unit_value_cents`, rounded half up to integer cents. The output basis is that rounded input share plus the order's `value_added_cents`. The output lot's `unit_value_cents` is the output basis divided by `output_quantity`, rounded half up to integer cents. This rounding order is fixed — round the input share, add the value added, then round the per-unit division — and reversing it produces different cents and is non-conformant. The output lot's `duty_rate` follows the source lot's `zone_status`: from a `PRIVILEGED_FOREIGN` source the source lot's locked rate carries over unchanged; from a `NON_PRIVILEGED_FOREIGN` or `ZONE_RESTRICTED` source the rate is re-derived from the tariff schedule at the `output_hts_code`; from a `DOMESTIC` source the rate is zero.

Two exits close an order without work. The `ZoneOperator` may reject a `REQUESTED` order, moving it to `REJECTED`. The owning importer may cancel an order in `REQUESTED` or `APPROVED` status — ownership and an `ACTIVE` zone required, audit hold not a blocker — moving it to `CANCELLED`; cancelling an order that was `APPROVED` releases the reservation by decreasing the source lot's `reserved_quantity` by the `input_quantity`, leaving `quantity_on_hand` untouched. Acting on an order outside these states yields `ERR_ORDER_INVALID_TRANSITION`.

### 3.5. Withdrawals for Consumption and Export

A **Withdrawal** removes merchandise from the zone, either into domestic commerce (`withdrawal_type` of `CONSUMPTION`) or out of the country (`EXPORT`). The owning importer creates one in `DRAFT` by supplying the `zone_id`, the `lot_id` to draw from, the `withdrawal_type`, and the `quantity` to withdraw (at least 1). The withdrawal's zone must be the lot's zone (otherwise `ERR_CROSS_ZONE_REFERENCE`), and the caller must own the lot — a lot whose `importer_ref` differs from the caller rejects with `ERR_NOT_RESOURCE_OWNER`; the server then stamps the withdrawal's own `importer_ref` from the caller. One prohibition is enforced at this earliest moment: a `CONSUMPTION` withdrawal against a `ZONE_RESTRICTED` lot is rejected with `ERR_ZR_CONSUMPTION_FORBIDDEN`, because zone-restricted merchandise may only ever be exported. At creation the server also computes a provisional `estimated_duty_cents` — the withdrawal `quantity` multiplied by the lot's `unit_value_cents` and `duty_rate`, rounded half up to integer cents, per the valuation rules of §3.3 — while `assessed_duty_cents` and `withdrawal_date` remain null and `duty_outcome` reads `PENDING`. Withdrawals may be listed with optional `zone_id`, `lot_id`, `weekly_entry_id`, `status`, and `withdrawal_type` filters.

Filing the withdrawal with customs is the point of no return for the merchandise. Filing requires the withdrawal to be `DRAFT` (otherwise `ERR_WITHDRAWAL_INVALID_TRANSITION`), the caller to own it, the zone to be `ACTIVE` with posture `NORMAL`, and the lot to be `IN_ZONE` (otherwise `ERR_LOT_NOT_IN_ZONE`). Availability is checked at this moment, not at creation: the `quantity` must be at most the lot's `quantity_on_hand` minus its `reserved_quantity`, with exact equality permitted (otherwise `ERR_INSUFFICIENT_QUANTITY`). If the withdrawal was attached at creation to a weekly entry, that entry must be `OPEN` (otherwise `ERR_ENTRY_NOT_OPEN`) and the logical clock's current instant must fall within the entry's week — on or after its `week_start_date` and strictly before its `week_end_date` — otherwise `ERR_WITHDRAWAL_OUTSIDE_ENTRY_WEEK`. Filing stamps `withdrawal_date` from the logical clock, computes the final `assessed_duty_cents` using the same formula as the estimate but against the merchandise as it stands at filing, and moves the withdrawal from `DRAFT` to `FILED`. The lot is then debited — `quantity_on_hand` decreased and `cumulative_withdrawn` increased by the withdrawal `quantity` — a lot left at zero on hand transitions from `IN_ZONE` to `DEPLETED`, and the zone's `active_lot_count` and `deferred_duty_exposure_cents` are recomputed; if the withdrawal is attached to a weekly entry, the entry's totals are recomputed as §3.6 describes.

From `FILED`, the two withdrawal types diverge. For a `CONSUMPTION` withdrawal, the owning importer pays the assessed duty, moving it to `DUTY_PAID` and setting `duty_outcome` to `COLLECTED`; paying requires the usual ownership, zone-`ACTIVE`, and posture-`NORMAL` gates, and paying an `EXPORT` withdrawal is rejected with `ERR_WRONG_WITHDRAWAL_TYPE`. For an `EXPORT` withdrawal, a `CustomsOfficer` confirms the export, moving it to `EXPORTED` and setting `duty_outcome` to `EXTINGUISHED` — export extinguishes the deferred duty and no duty is collected; confirming export on a `CONSUMPTION` withdrawal is likewise `ERR_WRONG_WITHDRAWAL_TYPE`, and both actions require the zone gates above. Once paid or exported, the withdrawal is terminal.

An importer may cancel a withdrawal in `DRAFT` or `FILED` status, given ownership and an `ACTIVE` zone; if the withdrawal is attached to a weekly entry, that entry must still be `OPEN` (otherwise `ERR_ENTRY_NOT_OPEN`). Cancellation moves the withdrawal to `CANCELLED` and sets `duty_outcome` to `NONE`. Cancelling a `DRAFT` withdrawal has no further effect, because nothing was debited. Cancelling a `FILED` withdrawal compensates the filing in full: the lot's `quantity_on_hand` is increased by the withdrawal `quantity`, its `cumulative_withdrawn` is decreased by the same amount, a lot thereby restored from zero on hand returns from `DEPLETED` to `IN_ZONE`, the zone aggregates are recomputed, and the attached entry's totals are recomputed. Any action on a withdrawal outside its valid states — including acting on a terminal withdrawal — yields `ERR_WITHDRAWAL_INVALID_TRANSITION`.

### 3.6. Weekly Entries and Merchandise Processing Fee Consolidation

Instead of paying a merchandise processing fee on every shipment, an importer may consolidate a week's consumption withdrawals into a single **WeeklyEntry**. The importer opens one by supplying the `zone_id` and a `week_start_date`; the entry starts in `OPEN` status, stamped with the creator's `importer_ref`, and it covers only that importer's withdrawals. The entry's `week_end_date` is derived as exactly seven days after `week_start_date`, and the entry week is the half-open interval that includes `week_start_date` and excludes `week_end_date`. Two entries on the same zone may not have overlapping weeks: because the interval is half-open, a new entry whose `week_start_date` coincides exactly with an existing entry's `week_end_date` is adjacent rather than overlapping and is permitted, but any true intersection is rejected with `ERR_WEEK_WINDOW_OVERLAP` (HTTP 409). At creation all six totals — `entered_value_cents`, `duty_total_cents`, `mpf_uncapped_cents`, `mpf_cents`, `per_shipment_mpf_cents`, and `mpf_savings_cents` — are initialized to zero. Entries may be listed with optional `zone_id` and `status` filters.

Membership is established at withdrawal creation and only there: a `CONSUMPTION` withdrawal may carry a `weekly_entry_id` attaching it to an entry, and that field can never be set later. The attached entry must belong to the same zone as the withdrawal (otherwise `ERR_CROSS_ZONE_REFERENCE`) and must belong to the same importer — an entry whose `importer_ref` differs from the caller rejects with `ERR_NOT_RESOURCE_OWNER`. Beyond existence, no further condition is imposed at attach time — in particular, the entry's status is not inspected: a withdrawal may be created attached to an entry that is no longer `OPEN`, and the `ERR_ENTRY_NOT_OPEN` requirement of §3.5 bites only when an attached withdrawal is filed or cancelled. The system clears `weekly_entry_id` itself in exactly one circumstance: the entry-freeze cascade of §3.7.

Filing the entry is the owning importer's act, requiring the entry to be `OPEN` (otherwise `ERR_ENTRY_INVALID_TRANSITION`), ownership, and the zone-`ACTIVE` and posture-`NORMAL` gates. Filing is only meaningful with content: at least one attached `CONSUMPTION` withdrawal must be in `FILED` or `DUTY_PAID` status, otherwise `ERR_ENTRY_NO_LINE_ITEMS`. Filing computes and stores the settlement, moving the entry from `OPEN` to `FILED`:

The settlement's member set is the attached withdrawals with `withdrawal_type` `CONSUMPTION` and status `FILED` or `DUTY_PAID`; `EXPORT` withdrawals and those still `DRAFT` or already `CANCELLED` never count. If the member set is empty, all six totals are zero and computation stops. Otherwise, each member line's value is its `quantity` multiplied by its lot's `unit_value_cents`, an exact integer-cent figure with no rounding. Each line's duty is that line value multiplied by the lot's `duty_rate`, rounded half up to integer cents per line first. The `entered_value_cents` is the sum of the line values. The `duty_total_cents` is the sum of the per-line rounded duties — summing the exact duties and rounding once at the end yields different cents and is non-conformant. The merchandise processing fee applies an ad valorem rate of 0.003464 to the entered value: `mpf_uncapped_cents` is `entered_value_cents` multiplied by that rate, rounded half up to integer cents. The consolidated `mpf_cents` then applies the statutory floor and ceiling: it is the uncapped fee raised to at least 3,000 cents (that is, $30.00) and capped at at most 60,000 cents ($600.00). To quantify the consolidation benefit, `per_shipment_mpf_cents` recomputes the fee hypothetically as if each member line had been entered separately — each line's value multiplied by 0.003464, rounded half up, floored at 3,000 cents and capped at 60,000 cents — and sums those per-line fees. Finally, `mpf_savings_cents` is `per_shipment_mpf_cents` minus `mpf_cents`. These totals are live: whenever membership or a member's status changes — a member withdrawal is filed, cancelled, or detached by an entry freeze — the totals are recomputed immediately, not only at filing.

Customs adjudicates a `FILED` entry through a transition action carrying `to_status`: `ACCEPTED` accepts the entry and is terminal, while `OPEN` returns it for correction, and the open–filed loop may repeat. Any other combination yields `ERR_ENTRY_INVALID_TRANSITION`. The fourth entry status, `FROZEN`, is never reachable through any client action: it arises only from the audit-hold cascade, and a frozen entry returns to `OPEN` only when the zone's posture clears, as §3.7 describes.

### 3.7. Annual Reconciliation and the Audit-Hold Cascade

Once per zone-year the `ZoneOperator` must reconcile the book record against a physical count. Creating an **AnnualReconciliation** takes the `zone_id`, the calendar `zone_year`, the operator-attested `beginning_value_cents` (at least 0), and the physical count's `physical_ending_value_cents` (at least 0). The reconciliation window for a zone year runs from the first instant of January 1 of `zone_year` (inclusive) to the first instant of January 1 of the following year (exclusive). Because creating a reconciliation for a zone-year that already has a `DRAFT` reconciliation legitimately supersedes that draft — the older draft moves silently to `SUPERSEDED` — the create cannot be rejected on observed state alone; it is instead guarded by the optimistic-concurrency rule of §2.7, so the request must carry `expected_zone_version` equal to the zone's current `version`, with a mismatch rejected as `ERR_STALE_ZONE_VERSION` (HTTP 412). A successful create also increments the zone's `version` by one. What creation may not do is stack on an active filing: if a reconciliation for the same zone and `zone_year` is already `SUBMITTED`, the create is rejected with `ERR_RECONCILIATION_ALREADY_SUBMITTED` (HTTP 409). The new reconciliation starts in `DRAFT`, and its six computed figures — `book_receipts_value_cents`, `book_withdrawals_value_cents`, `book_ending_value_cents`, `discrepancy_cents`, `discrepancy_pct`, and `audit_flagged` — remain null until submission. Reconciliations may be listed with optional `zone_id`, `zone_year`, and `status` filters.

Submission, again by the `ZoneOperator`, requires the reconciliation to be `DRAFT` (otherwise `ERR_RECONCILIATION_INVALID_TRANSITION`) and computes the variance between two legitimately divergent algorithms. The book side is forward-derived from system records: `book_receipts_value_cents` is the sum, over admissions in `ADMITTED` status whose `admission_date` falls inside the window, of each admission's `quantity` multiplied by its `unit_value_cents`; `book_withdrawals_value_cents` is the sum, over withdrawals in `FILED`, `DUTY_PAID`, or `EXPORTED` status whose `withdrawal_date` falls inside the window, of each withdrawal's `quantity` multiplied by its lot's `unit_value_cents` — withdrawals in `DRAFT` or `CANCELLED` status are excluded; and `book_ending_value_cents` is the beginning value plus receipts minus withdrawals. The physical side is the operator-supplied count. The `discrepancy_cents` is the physical ending value minus the book ending value. The `discrepancy_pct` handles the degenerate book first: when the book ending value is zero, the percentage is 0 if the physical count is also zero and 100 otherwise; in all other cases it is the absolute value of the discrepancy divided by the book ending value, multiplied by 100, rounded half up to four decimal places. The reconciliation is `audit_flagged` when that percentage is strictly greater than one-half of one percent — a variance of exactly 0.5 does not flag. Submission moves the reconciliation from `DRAFT` to `SUBMITTED`.

A flagged reconciliation triggers the audit-hold cascade, the widest-reaching automated sequence in the platform. The zone's `compliance_posture` moves from `NORMAL` to `AUDIT_HOLD`. Every weekly entry of that zone in `OPEN` status is frozen to `FROZEN`. Every withdrawal in `FILED` status attached to a freezing entry is forced back to `DRAFT`, its `weekly_entry_id` is cleared to null, and its quantity is restored to its lot: the lot's `quantity_on_hand` is increased by the withdrawal's `quantity` and its `cumulative_withdrawn` is decreased by the same amount. A lot restored from zero on hand by this restoration returns from `DEPLETED` to `IN_ZONE`, and the zone's `active_lot_count` and `deferred_duty_exposure_cents` are recomputed. From that moment until clearance, every workflow in §3 that declares the posture gate rejects with `ERR_ZONE_AUDIT_HOLD`.

Resolution comes from customs. A `CustomsOfficer` accepts a `SUBMITTED` reconciliation, moving it to the terminal `ACCEPTED` state; acting on a reconciliation in any other status yields `ERR_RECONCILIATION_INVALID_TRANSITION`. If the zone's posture is `AUDIT_HOLD` at that moment, acceptance clears it: the posture returns to `NORMAL`, and every `FROZEN` weekly entry reopens to `OPEN`. Withdrawals detached by the freeze stay `DRAFT` and are not re-attached to their former entries — the importer re-files or re-attaches nothing automatically, and any re-entry into a weekly entry is impossible because `weekly_entry_id` is settable only at creation.

### 3.8. Access Badges, Gate Events, and Zone Security

Physical access to the zone is controlled through **AccessBadge** records issued by the `ZoneOperator`. Issuing a badge takes the `zone_id`, the badge holder's full `holder_name`, an optional `employer_ref`, and a validity window from `valid_from` to `valid_until`. The window is a closed interval — both bounds inclusive — and `valid_until` must be strictly after `valid_from` or issuance fails schema validation with `ERR_INVALID_REQUEST`. A new badge starts in `ACTIVE` status. One holder may not hold overlapping credentials: if another badge exists for the same zone and the same `holder_name` with status `ACTIVE` or `SUSPENDED` whose closed validity window intersects the new badge's window — and because both intervals are closed, windows that merely touch at a boundary instant also conflict — issuance is rejected with `ERR_BADGE_WINDOW_OVERLAP` (HTTP 409). Badges may be listed with optional `zone_id`, `holder_name`, and `status` filters.

The operator manages the badge lifecycle through a transition action carrying `to_status`. An `ACTIVE` badge may be suspended to `SUSPENDED`, a `SUSPENDED` badge reinstated to `ACTIVE`, and a badge in either `ACTIVE` or `SUSPENDED` may be revoked to the terminal `REVOKED` state. Every badge transition requires the zone to be `ACTIVE` (otherwise `ERR_ZONE_NOT_ACTIVE`), and a `to_status` unreachable from the badge's current status yields `ERR_BADGE_INVALID_TRANSITION`.

Every passage through the zone's gates is recorded as a **ZoneAccessEvent** by a `GateOfficer`, supplying the `zone_id`, the `badge_id`, the `direction` (`IN` or `OUT`), and optionally `occurred_at`, which defaults to the logical clock's current instant when omitted. The event's zone must be the badge's zone (otherwise `ERR_CROSS_ZONE_REFERENCE`). Three standing rules make the log audit-grade. The cited badge must be `ACTIVE` at recording time — a gate event against a suspended or revoked badge is rejected with `ERR_BADGE_ACCESS_DENIED`. The event's `occurred_at` must fall inside the badge's closed validity window, on or after `valid_from` and on or before `valid_until`, otherwise `ERR_BADGE_WINDOW_VIOLATION`. And events for a given badge must strictly alternate, beginning with `IN`: an `IN` event is accepted only when the badge's recorded `IN` count equals its recorded `OUT` count, and an `OUT` event is accepted only when the recorded `IN` count exceeds the recorded `OUT` count by exactly one; any break in the alternation is rejected with `ERR_GATE_SEQUENCE_VIOLATION`. The log itself is append-only — events may be listed with optional `zone_id`, `badge_id`, and `direction` filters and read individually by any role, but never modified or deleted, consistent with the reduced property set of §2.4.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`; operations that modify an existing resource or drive a state transition return `200 OK`. Readers should reconstruct each endpoint's request payload, response body, and side effects from the workflow narratives of §3; the table below is an index, not a full contract.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/zones` | Create a zone (`ACTIVE`, posture `NORMAL`, zero exposure and lot count) | ZoneOperator |
| GET | `/zones` | List zones, paginated | All roles |
| GET | `/zones/{zoneId}` | Get one zone | All roles |
| POST | `/zones/{zoneId}/transition` | Operator lifecycle transition (`to_status` of `SUSPENDED`, `ACTIVE`, or `DEACTIVATED`) | ZoneOperator |
| POST | `/zones/admissions` | Create admission documentation in `DRAFT` | Importer |
| GET | `/zones/admissions` | List admissions with optional filters | All roles |
| GET | `/zones/admissions/{admissionId}` | Get one admission | All roles |
| POST | `/zones/admissions/{admissionId}/submit` | Submit an admission for customs review | Importer |
| POST | `/zones/admissions/{admissionId}/admit` | Admit merchandise into the zone; creates the inventory lot | CustomsOfficer |
| POST | `/zones/admissions/{admissionId}/return` | Return a submitted admission for correction | CustomsOfficer |
| POST | `/zones/admissions/{admissionId}/cancel` | Cancel a `DRAFT` or `SUBMITTED` admission | Importer |
| GET | `/zones/lots` | List inventory lots with optional filters | All roles |
| GET | `/zones/lots/{lotId}` | Get one inventory lot | All roles |
| POST | `/zones/manipulation-orders` | Request an in-zone manipulation or assembly order | Importer |
| GET | `/zones/manipulation-orders` | List manipulation orders with optional filters | All roles |
| GET | `/zones/manipulation-orders/{orderId}` | Get one manipulation order | All roles |
| POST | `/zones/manipulation-orders/{orderId}/approve` | Approve an order; reserves the input quantity on the source lot | ZoneOperator |
| POST | `/zones/manipulation-orders/{orderId}/complete` | Complete an approved order; consumes input units and creates the output lot | Importer |
| POST | `/zones/manipulation-orders/{orderId}/reject` | Reject a requested order | ZoneOperator |
| POST | `/zones/manipulation-orders/{orderId}/cancel` | Cancel a `REQUESTED` or `APPROVED` order; releases any reservation | Importer |
| POST | `/zones/withdrawals` | Create a withdrawal in `DRAFT`; optional weekly-entry attachment at creation | Importer |
| GET | `/zones/withdrawals` | List withdrawals with optional filters | All roles |
| GET | `/zones/withdrawals/{withdrawalId}` | Get one withdrawal | All roles |
| POST | `/zones/withdrawals/{withdrawalId}/file` | File a withdrawal with customs; debits the lot and assesses duty | Importer |
| POST | `/zones/withdrawals/{withdrawalId}/pay-duty` | Pay assessed duty on a `FILED` `CONSUMPTION` withdrawal | Importer |
| POST | `/zones/withdrawals/{withdrawalId}/confirm-export` | Confirm export of a `FILED` `EXPORT` withdrawal; extinguishes deferred duty | CustomsOfficer |
| POST | `/zones/withdrawals/{withdrawalId}/cancel` | Cancel a `DRAFT` or `FILED` withdrawal; a filed cancellation restores the lot | Importer |
| POST | `/zones/weekly-entries` | Open a weekly consolidated entry for a zone | Importer |
| GET | `/zones/weekly-entries` | List weekly entries with optional filters | All roles |
| GET | `/zones/weekly-entries/{entryId}` | Get one weekly entry | All roles |
| POST | `/zones/weekly-entries/{entryId}/file` | File the entry; computes entered value, duty total, capped MPF, and MPF savings | Importer |
| POST | `/zones/weekly-entries/{entryId}/transition` | Customs adjudication: `to_status` `ACCEPTED` accepts, `OPEN` returns for correction | CustomsOfficer |
| POST | `/zones/annual-reconciliations` | Create an annual reconciliation (OCC-guarded; supersedes an existing draft) | ZoneOperator |
| GET | `/zones/annual-reconciliations` | List annual reconciliations with optional filters | All roles |
| GET | `/zones/annual-reconciliations/{reconId}` | Get one annual reconciliation | All roles |
| POST | `/zones/annual-reconciliations/{reconId}/submit` | Submit; computes book-versus-physical variance and may trigger the audit-hold cascade | ZoneOperator |
| POST | `/zones/annual-reconciliations/{reconId}/accept` | Accept a `SUBMITTED` reconciliation; clears an audit hold if set | CustomsOfficer |
| POST | `/zones/access-badges` | Issue a zone access badge with a closed validity window | ZoneOperator |
| GET | `/zones/access-badges` | List access badges with optional filters | All roles |
| GET | `/zones/access-badges/{badgeId}` | Get one access badge | All roles |
| POST | `/zones/access-badges/{badgeId}/transition` | Badge lifecycle transition (`to_status` of `SUSPENDED`, `ACTIVE`, or `REVOKED`) | ZoneOperator |
| POST | `/zones/access-events` | Record a gate entry or exit event | GateOfficer |
| GET | `/zones/access-events` | List access events with optional filters | All roles |
| GET | `/zones/access-events/{eventId}` | Get one access event | All roles |
| POST | `/_clock/set_current_utc` | Set the server's logical clock | All roles |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is an index only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_ZONE_NOT_FOUND` | 404 Not Found |
| `ERR_ADMISSION_NOT_FOUND` | 404 Not Found |
| `ERR_LOT_NOT_FOUND` | 404 Not Found |
| `ERR_MANIPULATION_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_WITHDRAWAL_NOT_FOUND` | 404 Not Found |
| `ERR_WEEKLY_ENTRY_NOT_FOUND` | 404 Not Found |
| `ERR_RECONCILIATION_NOT_FOUND` | 404 Not Found |
| `ERR_BADGE_NOT_FOUND` | 404 Not Found |
| `ERR_ACCESS_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_ZONE_NOT_ACTIVE` | 409 Conflict |
| `ERR_ZONE_AUDIT_HOLD` | 409 Conflict |
| `ERR_ZONE_INVALID_TRANSITION` | 409 Conflict |
| `ERR_ZONE_NOT_EMPTY` | 409 Conflict |
| `ERR_ADMISSION_INVALID_TRANSITION` | 409 Conflict |
| `ERR_LOT_NOT_IN_ZONE` | 409 Conflict |
| `ERR_ORDER_INVALID_TRANSITION` | 409 Conflict |
| `ERR_WITHDRAWAL_INVALID_TRANSITION` | 409 Conflict |
| `ERR_WRONG_WITHDRAWAL_TYPE` | 409 Conflict |
| `ERR_ENTRY_INVALID_TRANSITION` | 409 Conflict |
| `ERR_ENTRY_NOT_OPEN` | 409 Conflict |
| `ERR_RECONCILIATION_INVALID_TRANSITION` | 409 Conflict |
| `ERR_BADGE_INVALID_TRANSITION` | 409 Conflict |
| `ERR_ZR_CONSUMPTION_FORBIDDEN` | 422 Unprocessable Entity |
| `ERR_MANIPULATION_NOT_PERMITTED` | 422 Unprocessable Entity |
| `ERR_BADGE_ACCESS_DENIED` | 422 Unprocessable Entity |
| `ERR_WEEK_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_BADGE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_WITHDRAWAL_OUTSIDE_ENTRY_WEEK` | 422 Unprocessable Entity |
| `ERR_BADGE_WINDOW_VIOLATION` | 422 Unprocessable Entity |
| `ERR_GATE_SEQUENCE_VIOLATION` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_QUANTITY` | 422 Unprocessable Entity |
| `ERR_LOT_BUSY` | 422 Unprocessable Entity |
| `ERR_ENTRY_NO_LINE_ITEMS` | 422 Unprocessable Entity |
| `ERR_RECONCILIATION_ALREADY_SUBMITTED` | 409 Conflict |
| `ERR_UNKNOWN_HTS_CODE` | 422 Unprocessable Entity |
| `ERR_CROSS_ZONE_REFERENCE` | 422 Unprocessable Entity |
| `ERR_BOND_CAPACITY_EXCEEDED` | 402 Payment Required |
| `ERR_STALE_ZONE_VERSION` | 412 Precondition Failed |
