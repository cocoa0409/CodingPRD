# Electric Outage Management API — Product Requirements Document

## 1. Introduction

When a major storm crosses an investor-owned electric utility's service territory, the control room confronts thousands of near-simultaneous telemetry events, a finite pool of crews, and a public that wants a restoration time it can trust. The difference between a well-run restoration and a chaotic one is procedural discipline: which outage receives the next available crew, what customers are told and when that promise may change, how mutual-aid crews are engaged, housed, and paid, and whether every dollar of storm cost survives regulatory and federal audit. This document specifies an outage management API that enforces that discipline end to end.

The system covers the full arc of storm response. Meter last-gasp messages, customer calls, and SCADA trips are ingested as trouble signals and promoted into tracked outages by a clustering rule; outages are confirmed, nested beneath upstream outages, merged when duplicates surface, and carried through assessment, repair, restoration, and verification. Estimated restoration times are published under a strict public-commit discipline with a locked horizon and capped extensions. Internal crews work under a fatigue ceiling; mutual-aid crews operate inside committed engagement windows with lodging blocks reserved against hotel inventory; switching orders move through a segregated issue/approve chain before energized work may start. Every labor hour, pole, transformer, hotel night, and penalty posts to a per-event cost ledger, and that ledger feeds per-county FEMA claims with a frozen eligibility snapshot at submission. All endpoints are mounted under `/om`. Every temporal rule in the system — restoration horizons, engagement windows, lodging nights, certification expiry, fatigue windows, eligibility windows — evaluates against a server-side logical clock (§2.4), never against wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through two mandatory HTTP headers: `X-User-ID`, which identifies the acting user, and `X-User-Role`, which specifies their operational capacity. A request in which either header is missing or empty is rejected with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400). A request whose `X-User-Role` is not among the roles authorized for the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

The system recognizes exactly nine roles, spelled as follows: `EmergencyDirector`, `Dispatcher`, `TelemetryGateway`, `FieldCrewLead`, `SystemOperator`, `MutualAidCoordinator`, `MaterialsManager`, `ClaimsOfficer`, and `Regulator`.

- An `EmergencyDirector` is the utility's emergency operations director and owns the storm-event lifecycle, the feeder registry, and the logical clock.
- A `Dispatcher` is a control-room dispatcher who runs signal clustering, manages outages and their restoration-time revisions, dispatches crews and work orders, verifies restoration, administers the priority-customer registry, and returns or accepts damage assessments.
- A `TelemetryGateway` is the automated metering and SCADA ingestion identity; it is the only role that may ingest trouble signals.
- A `FieldCrewLead` leads one internal crew and files and submits that crew's damage assessments; the lead may also mark arrival, start, and completion on their own crew's work orders.
- A `SystemOperator` is the switching authority and creates, issues, approves, executes, and aborts switching orders.
- A `MutualAidCoordinator` engages external crews and manages lodging blocks.
- A `MaterialsManager` administers warehouse stock pools and the requisition lifecycle.
- A `ClaimsOfficer` prepares, submits, certifies, and withdraws FEMA claims.
- A `Regulator` is an external regulator who obligates and pays certified claims.

All nine roles may read any resource through the API's read endpoints; write operations are restricted per the endpoint table in §4.

Identity semantics differ across roles. When `X-User-Role` is `FieldCrewLead`, `X-User-ID` is the `id` of the acting `Crew`; ownership checks on any resource that references a crew — a work order's assignee or a damage assessment's assessor — compare the resource's crew-reference field to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH` (HTTP 403). When `X-User-Role` is any of `EmergencyDirector`, `Dispatcher`, `TelemetryGateway`, `SystemOperator`, `MutualAidCoordinator`, `MaterialsManager`, `ClaimsOfficer`, or `Regulator`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it — for example as `issuer_user_id` on a switching order, `issued_by` on a system-exempt revision authored by a person, or `preparer_user_id` on a FEMA claim — but does not compare it to any entity's `id`.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock (§2.4).
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

List endpoints are paginated through two query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies how many items to skip and defaults to 0. A non-integer value for either parameter, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (400).

Unless a list states its own ordering, list endpoints return resources sorted by `created_at` in ascending order. Two lists override the default: an outage's revision history is ordered by `revision_seq` ascending, and the cost ledger is ordered by `posted_at` ascending with `created_at` ascending as the tie-break.

Paginated list responses include `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope; `has_more` is true exactly when `offset` plus the number of items returned is smaller than `total_count`.

### 2.4. The Logical Clock

A server-side logical clock is the single source of "now" for every temporal rule in the system: restoration-time horizons, mutual-aid engagement windows, lodging windows, certification expiry, signal freshness, fatigue windows, and the FEMA eligibility window all evaluate against it. Before the clock has ever been set, it reads exactly `2026-08-01T00:00:00Z`; it must never fall back to wall-clock time.

An admin-only, test-driving capability restricted to the `EmergencyDirector` sets the clock; the request payload carries `to_iso8601`, and the response reports the resulting `current_utc`. Advancing the clock performs a certification sweep: every priority customer whose `certification_status` is `CERTIFIED` and whose `certified_through` lies strictly before the new logical now transitions to `SUSPENDED`, and the sweep recomputes the affected feeder's `certified_priority_count` as well as `has_priority_customers` and `priority_score` on every non-terminal outage served by that feeder. Independently of the sweep, an outage's `etr_missed` flag is recomputed whenever the outage is read and whenever a revision is published.

### 2.5. Common Resource Properties

Most resources carry a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; it refreshes on every mutation.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by one on every mutation to the resource, including mutations cascaded from operations on related resources.

Three record types are append-style and carry only `id` and `created_at` — both `updated_at` and `version` are absent from them: trouble signals, ETR revisions, and cost ledger entries.

Every other timestamp field follows one of two representation rules. An instant the server computes itself is stamped from the logical clock (§2.4) and rendered in the same ISO 8601 UTC form with three fractional digits as `created_at`: this covers `activated_at`, `confirmed_at`, `restoration_reported_at`, `shift_started_at`, `arrived_at`, `completed_at`, `departed_at`, `posted_at`, the clock endpoint's reported `current_utc`, and every revision's `published_etr` — and therefore also `previous_etr` and an outage's `current_etr` — including when the request payload of a manual revision spelled the new `published_etr` in a different ISO 8601 form (for example without fractional digits). An instant the client supplies that is stored as sent — a trouble signal's `occurred_at`, a priority customer's `certified_through`, a mutual-aid crew's `committed_window_start` and `committed_window_end`, and a lodging block's `window_start` and `window_end` — is echoed back exactly as received. Every temporal rule in this document parses such values to instants before comparing them, so the spelling of a client-supplied timestamp never affects rule evaluation.

### 2.6. Cross-Entity Consistency and Version Semantics

State changes propagate across entity boundaries as a single atomic unit of work: every side effect of an operation commits within the triggering request, and every resource touched by the cascade — not just the resource named in the request — has its `updated_at` refreshed and its `version` incremented by one. When a single request performs several logically distinct mutations on the same resource (for example, accepting a damage assessment changes the outage's state and publishes a new ETR revision at once), the outage's `version` advances by exactly one for the whole request, never once per internal step.

Derived fields are reconciled immediately by the same request that invalidates them. Cost rollups on the storm event, a feeder's certified-customer count, an outage's priority indicators, and a stock pool's reserved and available quantities are never stale after the triggering call returns. The server may transition a related resource without an explicit client request against that resource when a cascade requires it — crews are released when their work disappears, requisitions are cancelled when their work order is cancelled, and child outages are re-parented when their parent is merged away.

### 2.7. Validation Order and Nested Path Resolution

Every request is validated against an ordered cascade of gates, and a failure at an earlier gate masks every later check — the client always receives the earliest applicable error. The gates, in order, are:

1. **Context.** The `X-User-ID` and `X-User-Role` headers must be present and non-empty (`ERR_MISSING_OR_INVALID_CONTEXT_HEADER`, 400).
2. **Role.** The presented role must be authorized for the endpoint (`ERR_FORBIDDEN_ROLE`, 403).
3. **Existence.** Resource identifiers in the path are validated left to right — for a nested path such as an outage's revision history, the outage's existence is confirmed before any revision is considered — and the request is rejected with `ERR_NOT_FOUND` (404) at the first identifier that does not correspond to an existing resource. Identifiers supplied in the request body (`feeder_id`, `storm_event_id`, `parent_outage_id`, `outage_id`, `crew_id`, `mutual_aid_crew_id`, `material_stock_id`, `work_order_id`, `lodging_block_id`, `target_outage_id`) are likewise validated for existence and fail with `ERR_NOT_FOUND`.
4. **State and posture.** The target resource's own state must permit the transition (`ERR_INVALID_STATE_TRANSITION`, 400). The resource's own state check fires before any cross-entity child-state check within this gate. This gate also carries the event-posture rejections (`ERR_EVENT_NOT_ACTIVE`, `ERR_EVENT_NOT_DEMOBILIZING`, `ERR_EVENT_CLOSED`, `ERR_EVENT_HAS_OPEN_WORK`, `ERR_LODGING_NOT_COMMITTED`, `ERR_PING_OUTAGE_STATE`, all 400) and the cross-entity child-state rejections (`ERR_OUTAGE_WORK_OPEN`, `ERR_OUTAGE_CHILDREN_OPEN`, `ERR_UNVERIFIED_WORK_REMAINS`, `ERR_RESTORE_PING_MISSING`, all 400).
5. **Safety and segregation.** On-site presence, switching-order execution, segregation of duties, and crew ownership (`ERR_SWITCHING_NOT_EXECUTED`, `ERR_CREW_NOT_ON_SITE` at 422; `ERR_SEGREGATION_OF_DUTIES` and `ERR_OWNERSHIP_MISMATCH` at 403).
6. **Referential integrity.** Cross-aggregate links must be coherent (`ERR_CROSS_EVENT_LINK`, `ERR_PARENT_OUTAGE_TERMINAL`, `ERR_MERGE_CYCLE`, `ERR_ASSESSMENT_REQUIRED`, all 422).
7. **Temporal windows.** Time-window rules (`ERR_ETR_IN_PAST`, `ERR_ETR_BACKWARD_FORBIDDEN`, `ERR_ETR_LOCKED_HORIZON`, `ERR_OUTSIDE_ENGAGEMENT_WINDOW`, `ERR_WINDOW_OUTSIDE_BLOCK`, `ERR_LODGING_WINDOW_OVERLAP`, `ERR_SIGNAL_IN_FUTURE`, `ERR_CERTIFICATION_WINDOW_PAST`, all 422).
8. **Constraint satisfaction.** Crew availability, crew-type match, and fatigue are checked in that order (`ERR_ETR_EXTENSION_EXCEEDS_CAP`, `ERR_CREW_TYPE_MISMATCH`, `ERR_CREW_NOT_AVAILABLE`, `ERR_FATIGUE_LIMIT_EXCEEDED`, `ERR_NO_ELIGIBLE_WORK` at 422; `ERR_ASSIGNEE_AMBIGUOUS` at 400; `ERR_DUPLICATE_STOCK` at 409.)
9. **Capacity and fiscal.** Rooms, stock, and the FEMA threshold are checked last (`ERR_NO_ROOMS_AVAILABLE`, `ERR_INSUFFICIENT_MATERIAL`, `ERR_FEMA_THRESHOLD_NOT_MET`, `ERR_LODGING_HAS_ACTIVE_CREWS`, all 422).

One endpoint-local exception to the gate order applies at trouble-signal ingestion (§3.2): there the `occurred_at`-in-the-future check fires before the restore ping's `outage_id` existence and outage-state checks, and before the rule that other signal types must not carry an `outage_id`. The per-endpoint prose in §3 and §2.11 likewise pins the order of checks within an operation where it states one explicitly.

Separately from the cascade, any request whose body is malformed — a missing required field, an invalid enum value, or a violated numeric constraint — is rejected with `ERR_INVALID_REQUEST` (400).

### 2.8. Optimistic Concurrency Control on Outage Records

Two write operations require the client to present the outage version it last observed, carried in a mandatory `expected_outage_version` field: publishing a manual ETR revision against an outage (`POST /om/outages/{id}/etr-revisions`) and accepting a damage assessment (`POST /om/damage-assessments/{id}/accept`). If the value does not equal the outage's current `version` — because another writer has advanced the outage since the client last read it — the request is rejected with `ERR_STALE_OUTAGE_VERSION` (HTTP 412). The version comparison is evaluated after the request's body validation, event-closure check, and state preconditions, and before the operation's remaining gates (for a manual revision, before the four publication gates of §2.11).

These two operations are exactly the cases where a stale view would otherwise go undetected: a new revision legitimately supersedes the current ETR without any state change, and accepting an assessment legitimately supersedes a previously accepted assessment, so no state precondition can catch a stale writer — the OCC check is the serialization point. No endpoint other than these two accepts a version field. Because many workflows advance an outage's `version` (confirmation, work bubbling, merges, revisions, verification failures), clients should re-read an outage before publishing a revision or accepting an assessment against it.

### 2.9. Money, Minutes, and Rounding

All monetary amounts are represented as integers of cents. Multiplication and division are performed at full internal precision, and rounding to whole cents uses the round-half-up method and is applied only at the step each calculation pins: the labor posting rounds at posting time; the mutual-aid early-release penalty rounds only at the final penalty step; each lodging crew share is rounded before the shares are summed, and the block total is rounded separately. Restoration-time arithmetic works at whole-minute precision, with the round-half-up step of each formula applied exactly where that formula pins it. Timestamps compared against one another use the logical clock (§2.4).

### 2.10. The Event Cost Ledger

Every dollar of storm cost is recorded as an append-only `CostLedgerEntry`. Each entry carries the `storm_event_id` it accrues to, the originating `work_order_id` for labor and material entries (null for mutual-aid engagement and lodging entries), an `entry_type` of `LABOR_INTERNAL`, `LABOR_MUTUAL_AID`, `MATERIAL`, `LODGING`, or `MUTUAL_AID_PENALTY`, a signed `amount_cents`, the logical timestamp `posted_at`, and a `reversed_entry_id` that is null on originals and references the reversed entry on reversal entries only. Reversals never delete history: a reversal is a new entry carrying the negated amount, so originals and reversals coexist.

An entry's `cost_class` is `CAPITAL` when it is a labor or material entry arising from a work order of type `REPLACE_POLE` or `REPLACE_TRANSFORMER`, and `O_AND_M` in every other case; mutual-aid and lodging entries are always `O_AND_M`. County attribution follows the cost's origin: labor and material entries take the county of the affected outage's feeder, mutual-aid entries take the crew's `service_county_code`, and lodging entries take the block's `county_code`.

From the ledger, the storm event maintains seven computed totals, each a plain sum over all of the event's entries — originals and reversals alike, so reversals net out: `total_labor_cents` over `LABOR_INTERNAL` and `LABOR_MUTUAL_AID`, `total_material_cents` over `MATERIAL`, `total_mutual_aid_cents` over `LABOR_MUTUAL_AID` and `MUTUAL_AID_PENALTY`, `total_lodging_cents` over `LODGING`, `total_event_cost_cents` over every entry regardless of type, and `capital_cost_cents` and `om_cost_cents` splitting all entries by `cost_class`. These totals are recomputed immediately on every posting and are exposed on the event record and through the event's cost-summary read.

### 2.11. Restoration-Time Publication Discipline

An outage's `current_etr` always mirrors the `published_etr` of its highest-sequence revision and is null until the first revision exists. Each revision is an immutable `EtrRevision` record carrying the `outage_id`, a per-outage monotonic `revision_seq` starting at 1, a `revision_reason` (`INITIAL`, `DAMAGE_FOUND`, `CREW_DELAYED`, `NESTED_DISCOVERED`, `WEATHER_DELAY`, `CORRECTION`, or `VERIFICATION_FAILED`), the `published_etr`, the `previous_etr` (null on sequence 1), and `issued_by` — the revising dispatcher's `X-User-ID`, or the literal string `system` for automatic revisions.

Four gates govern every manual revision a dispatcher publishes, in the order given. First, the new `published_etr` must lie strictly after the logical now — a published ETR is always in the future — otherwise the request is rejected with `ERR_ETR_IN_PAST` (422). Second, a backward revision, one earlier than the outage's current `current_etr`, is allowed only with reason `CORRECTION` and only while the outage is in `CONFIRMED` or `ASSESSED`; any other backward revision is rejected with `ERR_ETR_BACKWARD_FORBIDDEN` (422), and once the current ETR has been missed (the logical now is past `current_etr`), a `CORRECTION` is always rejected. Third, an extension may move the published time later by at most 360 minutes (six hours) in a single revision unless the reason is `DAMAGE_FOUND`, which is uncapped; an extension of exactly 360 minutes is allowed, while one minute more is rejected with `ERR_ETR_EXTENSION_EXCEEDS_CAP` (422). Fourth, a public-commit lock horizon protects imminent promises: when the logical now falls within the thirty minutes before the current ETR, inclusive of both ends of that window, every manual revision is rejected with `ERR_ETR_LOCKED_HORIZON` (422) unless the reason is `NESTED_DISCOVERED`; once the ETR has been missed, the lock no longer applies.

System-issued revisions — the provisional revision created at confirmation, the damage-driven revision created when an assessment is accepted, and the verification-failure revision — are exempt from the backward, cap, and lock gates. On every successful revision the server assigns the next `revision_seq` for the outage, records the outgoing value in `previous_etr`, sets `current_etr` to the new instant, increments the outage's `version` by one, and recomputes `etr_missed`.

### 2.12. Crew Fatigue and Segregation-of-Duties Safeguards

No internal crew may be assigned work that would push its projected continuous work past sixteen hours. The projection is the crew's `worked_minutes_this_shift` plus an estimate for the candidate outage — the `estimated_repair_minutes` of the outage's accepted assessment, or a default of two hours when no accepted assessment exists. The ceiling is 960 minutes: a projection of exactly 960 minutes is allowed, while 961 minutes or more is rejected with `ERR_FATIGUE_LIMIT_EXCEEDED` (422).

Two segregation-of-duties rules are absolute. A switching order's approver must be a different `SystemOperator` than its issuer, and a FEMA claim's certifier must be a different `ClaimsOfficer` than its preparer; either violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (403). In parallel, a `FieldCrewLead` may act only on their own crew's work orders and assessments, and a switching order may be issued only by the operator who created it; violations are rejected with `ERR_OWNERSHIP_MISMATCH` (403).

## 3. Business Logic & Workflows

### 3.1. Declaring the Event and Registering the Grid

Storm response begins when an `EmergencyDirector` declares a storm event with an `event_name` and an `event_type` — one of `THUNDERSTORM`, `HURRICANE`, `ICE_STORM`, `WILDFIRE_PSPS`, or `TORNADO`. A new event starts in `DECLARED`. Activation moves it to `ACTIVE` and stamps `activated_at` with the logical now; the field remains null until then. The event record also exposes `open_outage_count`, the number of its outages whose `outage_status` is neither `VERIFIED` nor `CANCELLED`, alongside the seven cost totals described in §2.10. The event list can be filtered by `event_status`.

Before or during an event, the director registers feeders. A feeder carries a `feeder_code`, the `county_code` it serves (the unit by which FEMA claims are later evaluated), and a `service_customer_count` of at least one. Two thresholds tune cluster promotion: `cluster_signal_threshold`, the meter last-gasp count at or above which a cluster becomes an outage, defaults to 3, and `cluster_call_threshold`, the customer-call count with the same effect, defaults to 5; an operator may override either at registration, and both must be at least 1. Each feeder also exposes `certified_priority_count`, the number of priority customers on it whose certification is currently `CERTIFIED`.

The priority-customer registry is the dispatch floor's view of medical and infrastructural risk. A `Dispatcher` registers a customer with an `account_ref`, a `priority_class` of `LIFE_SUPPORT` or `CRITICAL_FACILITY`, and the `feeder_id` of the serving feeder; the record starts in `REGISTERED`. Certification moves a customer from `REGISTERED` to `CERTIFIED` — and likewise rehabilitates a `SUSPENDED` customer back to `CERTIFIED` — but only when the supplied `certified_through` instant lies strictly after the logical now; a date already in the past is rejected with `ERR_CERTIFICATION_WINDOW_PAST`. Certification sets `certified_through` and immediately recomputes the feeder's `certified_priority_count` plus `has_priority_customers` and `priority_score` on every non-terminal outage on that feeder. When the logical clock later advances past a customer's `certified_through`, the sweep described in §2.4 moves the customer from `CERTIFIED` to `SUSPENDED` with the same recomputation; a `SUSPENDED` customer no longer contributes to any count or score. Decertification is the terminal act: from `REGISTERED`, `CERTIFIED`, or `SUSPENDED`, a dispatcher may move a customer to `DECERTIFIED`, again triggering the feeder and outage recomputation. The registry list can be filtered by `feeder_id` or `certification_status`.

### 3.2. From Telemetry to Trouble: Signal Ingestion and Cluster Promotion

The `TelemetryGateway` ingests every field signal as a trouble signal: a `signal_type` of `METER_LAST_GASP`, `CUSTOMER_CALL`, `SCADA_TRIP`, or `METER_RESTORE_PING`, the `feeder_id` it originated on, and the `occurred_at` instant, which must not lie after the logical now — a signal from the future is rejected with `ERR_SIGNAL_IN_FUTURE`. A restore ping is the special case: its payload must also carry the `outage_id` of the outage it reports restoration for, that outage must currently be in `WORKING` or `RESTORED` (otherwise the ingest is rejected with `ERR_PING_OUTAGE_STATE`), and the ping is born `CLUSTERED` with its `outage_id` set from the payload. Every other signal type must not carry an `outage_id` — one that does is rejected with `ERR_INVALID_REQUEST` — and is born `UNCLUSTERED`. Signals carry no `updated_at` or `version`; the signal list can be filtered by `feeder_id`, `outage_id`, `signal_type`, or `disposition`.

Clustering turns noise into work. A `Dispatcher` runs the promotion pass against an `ACTIVE` event — running it against an event in any other posture is rejected with `ERR_EVENT_NOT_ACTIVE` — naming a `feeder_id` in the payload. The pass considers that feeder's `UNCLUSTERED` signals of type `METER_LAST_GASP`, `CUSTOMER_CALL`, or `SCADA_TRIP` (restore pings never participate), ordered by `occurred_at` ascending with `created_at` ascending as the tie-break — never by identifier. The earliest candidate anchors a single group: every candidate whose `occurred_at` falls within sixty minutes of the anchor's, the end of the window included. The group promotes to an outage when at least one `SCADA_TRIP` is present in it, or when the count of last-gasp signals reaches the feeder's `cluster_signal_threshold`, or when the count of customer calls reaches its `cluster_call_threshold`; a count exactly equal to a threshold promotes, while one short of the threshold does not.

On promotion the system creates an outage on the event and feeder in `SUSPECTED` — its `customers_affected` stays null until confirmation — and moves every signal in the group to `CLUSTERED` with its `outage_id` pointing at the new outage. The pass responds `200 OK` with a summary object reporting `promoted`, the new `outage_id`, and the `clustered_signal_count`; when no eligible candidate exists or the anchored group fails to promote, the summary reports `promoted` false with `outage_id` null and `clustered_signal_count` 0. Only the one anchored group is evaluated per run, so repeated runs promote further groups; when a group fails to promote, all of its candidates remain `UNCLUSTERED` and may accumulate across runs, with each later run re-anchoring at the earliest still-unclustered signal.

### 3.3. The Outage Record: Confirmation, Nesting, and Cancellation

Clustering is not the only way an outage comes into being: a `Dispatcher` may file one manually with a payload containing the `storm_event_id` and `feeder_id`. Manual creation requires the event to be `ACTIVE` (`ERR_EVENT_NOT_ACTIVE`), and the new record starts in `SUSPECTED`. Passing an optional `parent_outage_id` files the outage as nested beneath an upstream outage — a downed lateral beneath a downed trunk, for instance. The parent must belong to the same storm event (`ERR_CROSS_EVENT_LINK`) and must not already be in `VERIFIED` or `CANCELLED` (`ERR_PARENT_OUTAGE_TERMINAL`); root outages leave `parent_outage_id` null. The outage list can be filtered by `storm_event_id`, `feeder_id`, `parent_outage_id`, `merged_into_outage_id`, or `outage_status`.

Confirmation is the moment a suspicion becomes a commitment. Confirming a `SUSPECTED` outage requires a `cause_code` — one of `TREE`, `LIGHTNING`, `EQUIPMENT`, `VEHICLE`, or `UNKNOWN` — and a `customers_affected` count of at least one; a missing cause or a count below one is rejected as an invalid request. Confirmation stamps `confirmed_at` with the logical now and publishes the outage's first ETR revision: sequence 1, reason `INITIAL`, `issued_by` recorded as the literal string `system`. Its `published_etr` is computed provisionally from what is known before any field assessment — a base of 120 minutes of preparation, plus the smaller of `customers_affected` and five thousand multiplied by two minutes per customer and by a cause factor, that multiplication rounded half up to a whole minute before being added to the base. The cause factor is 1.5 for `TREE`, 1.2 for `LIGHTNING`, 1.0 for `EQUIPMENT`, 1.3 for `VEHICLE`, and 1.4 for `UNKNOWN`. The published instant is `confirmed_at` plus the total, and `current_etr` is set to it. The whole confirmation advances the outage's `version` by one and recomputes its `priority_score`.

The `priority_score` is the dispatch ranking number, an integer sum of five components: ten thousand points when a `CERTIFIED` priority customer of class `LIFE_SUPPORT` exists on the outage's feeder; four thousand when a `CERTIFIED` `CRITICAL_FACILITY` customer exists on the feeder; the smaller of `customers_affected` and ten thousand; fifty points for each whole hour elapsed since `confirmed_at`, discarding any partial hour; and two thousand when `etr_missed` is currently true. Alongside it, the outage exposes `has_priority_customers`, true while any `CERTIFIED` priority customer exists on its feeder, and `etr_missed`, true whenever the logical now has passed `current_etr` and recomputed on read and on every revision. The score is recomputed at confirmation, at every ETR revision, when a clock sweep or a certification change alters the feeder's certified set, when a merge transfers customers onto the outage, and on read.

Two exits remove a suspected or confirmed outage without restoration. A false-alarm cancellation — available only from `SUSPECTED` or `CONFIRMED`, and only while no work orders exist for the outage at all, otherwise `ERR_OUTAGE_WORK_OPEN` — moves the outage to `CANCELLED`, transitions every signal clustered to it from `CLUSTERED` to `DISMISSED`, and increments its `version`. A merge instead retires a duplicate into a surviving outage: the payload carries `target_outage_id`, and the merge is permitted from `SUSPECTED`, `CONFIRMED`, or `ASSESSED`. The target must belong to the same storm event (`ERR_CROSS_EVENT_LINK`), must not be `VERIFIED` or `CANCELLED` (`ERR_INVALID_STATE_TRANSITION`), and must be neither the source itself nor one of its transitive descendants — the server walks the `parent_outage_id` chain to check — (`ERR_MERGE_CYCLE`). The merge records the target in the source's `merged_into_outage_id`, re-links every signal clustered to the source onto the target while keeping them `CLUSTERED`, and, when the source had reached `CONFIRMED` or `ASSESSED`, adds the source's `customers_affected` into the target's count and recomputes the target's `priority_score`. Every non-terminal work order on the source is cancelled, with any internal crew en route on one released from `EN_ROUTE` back to `AVAILABLE`; every child outage of the source is re-parented so its `parent_outage_id` points at the target; and the `version` of both source and target increments by one. The merge response carries the retired source outage.

### 3.4. Damage Assessment and the Life of an ETR

Once an outage is `CONFIRMED`, `ASSESSED`, or `WORKING`, a `FieldCrewLead` opens a damage assessment against it by naming the `outage_id` and reporting a `damage_class` of `MINOR`, `MAJOR`, or `CATASTROPHIC`, an `estimated_repair_minutes` of at least one, and whether `requires_switching` is true. The lead's `X-User-ID` must identify an existing crew record, which the server records as `assessor_crew_id`; if no such crew exists the request is rejected with `ERR_INVALID_REQUEST` (400). The assessment starts in `DRAFT`. Submission moves it to `SUBMITTED` and is restricted to the assessing crew itself — a lead acting on another crew's assessment is rejected with `ERR_OWNERSHIP_MISMATCH`. A dispatcher may hand a `SUBMITTED` assessment back to `DRAFT` for rework. An outage's assessments can be listed as a sub-resource in `created_at` order, and the global assessment list filters by `outage_id`, `assessor_crew_id`, or `assessment_status`.

Acceptance is where field truth rewrites the public promise. A `Dispatcher` accepts a `SUBMITTED` assessment — moving it to `ACCEPTED` — by presenting `expected_outage_version` equal to the linked outage's current `version` — a mismatch is rejected with `ERR_STALE_OUTAGE_VERSION` (412), per §2.8 — and the linked outage must be in `CONFIRMED`, `ASSESSED`, or `WORKING` (`ERR_INVALID_STATE_TRANSITION`). Acceptance cascades: any other assessment on the same outage currently `ACCEPTED` transitions to `SUPERSEDED`; if the outage was `CONFIRMED` it advances to `ASSESSED`; and the system publishes a new revision with reason `DAMAGE_FOUND`, `issued_by` recorded as `system`, whose `published_etr` uses the post-assessment variant of the estimate. In that variant, a crew factor of 1.0 applies when any non-cancelled work order on the outage already has an internal or mutual-aid assignee, and 1.5 when none does; the repair component is the accepted assessment's `estimated_repair_minutes` multiplied by that factor, rounded half up to a whole minute — the rounding is pinned here, before any overhead is added — and when the accepted assessment's `requires_switching` is true, a forty-five-minute switching overhead is added on top. The published instant is the acceptance time plus the total, and `current_etr` moves to it. The entire accept request advances the outage's `version` by exactly one — state change, supersession, and revision together — and recomputes `priority_score`.

Because the pieces lean on each other — the priority score reads `etr_missed`, which reads `current_etr`, while the crew factor depends on assignment state — the server evaluates an acceptance in a fixed order: scoring and dispatch ranking observe the pre-revision `current_etr`, assignment effects then take place, and the ETR recomputation observes the post-assignment crew factor. Ranking inputs are never re-derived from the ETR being computed within the same request.

Dispatchers may also publish manual revisions against an outage's history, subject to the four publication gates of §2.11 and to the same `expected_outage_version` OCC guard, which is evaluated against the outage's current `version` and fails with `ERR_STALE_OUTAGE_VERSION` (412). A manual revision is accepted only while the outage is in `CONFIRMED`, `ASSESSED`, `WORKING`, or `RESTORED`; against a `SUSPECTED`, `VERIFIED`, or `CANCELLED` outage the publication is rejected with `ERR_INVALID_STATE_TRANSITION`. A manual revision carries the `published_etr`, one of the seven `revision_reason` values, and the OCC token; on success it becomes the outage's highest-sequence record and its `published_etr` becomes the new `current_etr`. The full history is readable per outage, ordered by `revision_seq` ascending.

### 3.5. Crews, Work Orders, and the Dispatch Pipeline

Internal crews are registered by a `Dispatcher` with a `crew_code`, a `crew_type` of `LINE`, `TREE`, `DAMAGE_ASSESSOR`, or `SUBSTATION`, a `home_base` depot, and an `hourly_rate_cents` of at least zero. A crew's `crew_status` starts at `OFF_DUTY`. Starting a shift moves it to `AVAILABLE`, stamps `shift_started_at` with the logical now, and resets the fatigue baseline; ending a shift returns the crew to `OFF_DUTY` and is accepted only from `AVAILABLE` — a crew that is `EN_ROUTE` or `ON_SITE` on any non-terminal work order cannot go off duty, and the attempt is rejected with `ERR_INVALID_STATE_TRANSITION`. A crew's `worked_minutes_this_shift` is computed as the sum, over the work orders this crew has completed since `shift_started_at`, of the minutes between each order's `arrived_at` and `completed_at`, plus — while the crew is currently `ON_SITE` on an `IN_PROGRESS` order — the minutes from that order's `arrived_at` to the logical now.

Work itself is decomposed into work orders. A dispatcher creates one with the `outage_id` being worked, a `work_type` of `ASSESSMENT`, `REPAIR`, `REPLACE_POLE`, `REPLACE_TRANSFORMER`, or `SWITCHING`, a `required_crew_type`, and a `requires_switching_order` flag that, when true, bars the order from starting until an executed switching order authorizes it. Creation itself is not gated on the linked outage's status (a `CLOSED` event still rejects it per §3.9); the readiness transition below is what examines the outage's state. A work order carries two independent status dimensions from birth: `execution_status` begins at `CREATED`, and `verification_status` begins at `PENDING_VERIFY`. The work-order list filters by `outage_id`, `assigned_crew_id`, `assigned_mutual_aid_crew_id`, `switching_order_id`, or `execution_status`.

Readying moves an order from `CREATED` to `READY` and is the dispatcher's declaration that the work is plannable: the linked outage must be in `CONFIRMED`, `ASSESSED`, or `WORKING` (`ERR_INVALID_STATE_TRANSITION`), and for any `work_type` other than `ASSESSMENT`, at least one damage assessment on the linked outage must be `ACCEPTED` — readiness without field truth is rejected with `ERR_ASSESSMENT_REQUIRED`.

Assignment moves a `READY` order to `DISPATCHED`. The payload names exactly one assignee: a `crew_id` for an internal crew or a `mutual_aid_crew_id` for an external one. Supplying both is rejected with `ERR_ASSIGNEE_AMBIGUOUS` (400); supplying neither is rejected with `ERR_INVALID_REQUEST`. An internal assignee must be `AVAILABLE` (`ERR_CREW_NOT_AVAILABLE`), its `crew_type` must equal the order's `required_crew_type` (`ERR_CREW_TYPE_MISMATCH`), and the fatigue projection of §2.12 must hold (`ERR_FATIGUE_LIMIT_EXCEEDED`). A mutual-aid assignee must be in `AVAILABLE` status (`ERR_CREW_NOT_AVAILABLE`), must match `required_crew_type` (`ERR_CREW_TYPE_MISMATCH`), and the logical now must fall within its committed engagement window, the start inclusive and the end exclusive (`ERR_OUTSIDE_ENGAGEMENT_WINDOW`). Assignment records the choice in `assigned_crew_id` or `assigned_mutual_aid_crew_id` — once dispatched, exactly one of the two is non-null — and an internal assignee transitions from `AVAILABLE` to `EN_ROUTE`, while a mutual-aid crew remains `AVAILABLE` in its own status dimension even while assigned.

When the control room simply wants the next job for a free crew, the dispatcher invokes the event-scoped selector with the `crew_id` of an `AVAILABLE` internal crew. The eligible set is every work order in `READY` whose `required_crew_type` matches the crew's `crew_type` and whose outage belongs to that event and is neither `VERIFIED` nor `CANCELLED`; the selector picks the order whose outage has the highest `priority_score`, breaking ties by the work order's `created_at`, earliest first — never by identifier. An empty eligible set is rejected with `ERR_NO_ELIGIBLE_WORK`. The eligible set is evaluated before the named crew's availability, so an empty set yields `ERR_NO_ELIGIBLE_WORK` even when the crew is not `AVAILABLE`. A successful selection dispatches exactly as a manual assignment does, fatigue check included.

Arrival, start, and completion close the field loop. Marking arrival — by the assigned `FieldCrewLead` or a `Dispatcher` — requires the order to be `DISPATCHED`, stamps the order's `arrived_at`, and moves the internal crew from `EN_ROUTE` to `ON_SITE`. Starting requires the assigned internal crew to be `ON_SITE` (`ERR_CREW_NOT_ON_SITE`); mutual-aid assignments skip the on-site check. When `requires_switching_order` is true, the switching order recorded on the work order must have reached `EXECUTED`, otherwise the start is rejected with `ERR_SWITCHING_NOT_EXECUTED`. Starting moves the order to `IN_PROGRESS`, and when it is the first non-cancelled order on its outage to do so while the outage is `CONFIRMED` or `ASSESSED`, the outage bubbles to `WORKING` — a single version increment covers the whole start request.

Completion stamps `completed_at`, releases an internal crew from `ON_SITE` back to `AVAILABLE`, and accrues the worked minutes into `worked_minutes_this_shift`. For an internal crew only, completion also posts the labor cost: the minutes between `arrived_at` and `completed_at`, multiplied by the crew's `hourly_rate_cents` and divided by sixty, rounded half up to whole cents — thirty minutes at an hourly rate of 10,001 cents posts 5,001 cents. The entry's type is `LABOR_INTERNAL`, its county is the outage's feeder's county, and its class follows §2.10. A mutual-aid-assigned order posts no labor entry at completion; that cost is settled when the crew departs. If the order had previously failed verification, this re-completion returns `verification_status` from `VERIFY_FAILED` to `PENDING_VERIFY`.

Cancellation is available from `CREATED`, `READY`, or `DISPATCHED`. Cancelling releases an internal crew that was en route — `EN_ROUTE` back to `AVAILABLE`, with `assigned_crew_id` cleared — and cascades to materials: every requisition on the order still in `REQUESTED` moves to `CANCELLED`, and every one in `STAGED` moves to `CANCELLED` while releasing its reservation back to the stock pool.

When every work order on a `WORKING` outage has reached `COMPLETED` or `CANCELLED` and at least one has genuinely completed — otherwise the report is rejected with `ERR_OUTAGE_WORK_OPEN` — the dispatcher reports the outage restored, moving it to `RESTORED` and stamping `restoration_reported_at` with the logical now. Restoration of a parent says nothing about its nested outages: children in `CONFIRMED`, `ASSESSED`, or `WORKING` remain open and must be worked to their own conclusions.

### 3.6. Switching Authority and Field Verification

Energized work that must be de-energized, sectionalized, or paralleled runs under a switching order. A `SystemOperator` creates one for a non-terminal work order — creating against a `COMPLETED` or `CANCELLED` order is rejected with `ERR_INVALID_STATE_TRANSITION` — supplying the `work_order_id` and the `switching_steps`, an ordered list that must contain at least one step. The creator's `X-User-ID` is recorded as `issuer_user_id`, the order starts in `DRAFT`, and the work order's `switching_order_id` is set to point at it. The switching-order list filters by `work_order_id` or `so_status`.

Issuance moves the order from `DRAFT` to `ISSUED` and is restricted to the issuer — any other operator is rejected with `ERR_OWNERSHIP_MISMATCH`. Once issued, an order can never return to `DRAFT`: that transition does not exist and is rejected with `ERR_INVALID_STATE_TRANSITION`, so a mistaken order must be aborted and a fresh one created. Approval moves `ISSUED` to `APPROVED`, but segregation of duties applies — the approver's `X-User-ID` must differ from `issuer_user_id`, else `ERR_SEGREGATION_OF_DUTIES` — and is recorded in `approver_user_id`. Execution moves `APPROVED` to `EXECUTED` and is gated twice: the linked work order must be non-terminal (`ERR_INVALID_STATE_TRANSITION`), and the outage's storm event must still be `ACTIVE` (`ERR_EVENT_NOT_ACTIVE`). Aborting from `DRAFT`, `ISSUED`, or `APPROVED` moves the order to `ABORTED` and clears the work order's `switching_order_id`, so a switching-gated order needs a fresh executed order before it can start.

Verification is the work order's second, parallel dimension. Once an order is `COMPLETED` — verifying in any other execution state is rejected with `ERR_INVALID_STATE_TRANSITION` — a `Dispatcher` records an `outcome` of `PASSED` or `FAILED`. A pass moves `verification_status` from `PENDING_VERIFY` to `VERIFY_PASSED`, terminal for that dimension. A failure cascades across both dimensions: `verification_status` becomes `VERIFY_FAILED`, `execution_status` reopens from `COMPLETED` back to `IN_PROGRESS`, and `completed_at` clears; on the linked outage, the system publishes a revision with reason `VERIFICATION_FAILED`, `issued_by` recorded as `system`, and a `published_etr` exactly three hours (180 minutes) after the logical now, updating `current_etr` and advancing the outage's `version` by one. The rework loop closes when the crew re-completes the order, which returns `verification_status` to `PENDING_VERIFY` for a fresh judgment.

Final verification of the outage itself is the dispatcher's last word. Verifying a `RESTORED` outage checks three things: every child outage nested beneath it must be in `VERIFIED` or `CANCELLED` (`ERR_OUTAGE_CHILDREN_OPEN`); every non-cancelled work order on it must carry `VERIFY_PASSED` (`ERR_UNVERIFIED_WORK_REMAINS`); and at least one `CLUSTERED` trouble signal of type `METER_RESTORE_PING` pointing at this outage must have an `occurred_at` at or after `restoration_reported_at` (`ERR_RESTORE_PING_MISSING`). When all three hold, the outage moves to `VERIFIED`, terminal, with its `version` incremented.

### 3.7. Mutual Aid and Lodging Logistics

Big storms borrow crews. A `MutualAidCoordinator` engages an external crew for an event by naming the `storm_event_id`, the `company_name`, a `crew_type` from the same four-value trade list internal crews use, a `roster_size` of at least one, the `service_county_code` its costs will be attributed to, a `daily_rate_cents` and a `per_diem_cents` each at least zero, and a committed engagement window from `committed_window_start` (inclusive) to `committed_window_end` (exclusive), the end strictly after the start. The engagement starts in `REQUESTED`. The crew list filters by `storm_event_id`, `lodging_block_id`, or `ma_status`.

Arrival must happen inside the commitment: marking a crew arrived moves it from `REQUESTED` to `AVAILABLE` only when the logical now falls within the committed window — start inclusive, end exclusive — (`ERR_OUTSIDE_ENGAGEMENT_WINDOW`) and the event is `ACTIVE` (`ERR_EVENT_NOT_ACTIVE`); it stamps `arrived_at`. From `AVAILABLE` the crew can be dispatched to work orders exactly as an internal crew can, though its own status stays `AVAILABLE` while assigned. Demobilization moves `AVAILABLE` to `DEMOBILIZING` and is refused while any work order assigned to the crew is `DISPATCHED` or `IN_PROGRESS` (`ERR_INVALID_STATE_TRANSITION`); demobilization also releases lodging, clearing the crew's `lodging_block_id` and decrementing the block's `rooms_allocated` by the crew's `roster_size`. A crew still in `REQUESTED` may instead be cancelled outright to `CANCELLED`; such a crew never holds lodging, because room assignment is only possible once a crew is `AVAILABLE`.

Lodging is contracted as room blocks. The coordinator creates a block with the `storm_event_id`, a `hotel_name`, the `county_code` the cost is attributed to, a `room_count` of at least one, a `nightly_rate_cents` of at least zero, and a stay window from `window_start` (the first night, inclusive) to `window_end` (checkout day, exclusive) that must span a whole number of twenty-four-hour nights. The uniqueness and overlap scope is the pair of storm event and hotel: a new block whose window overlaps an existing block for the same event and `hotel_name` under half-open interval semantics — touching at an endpoint does not overlap — is rejected with `ERR_LODGING_WINDOW_OVERLAP`. A block starts `OPEN`; committing moves it to `COMMITTED` and makes it assignable. The block list filters by `storm_event_id` or `block_status`.

Assigning a crew to a block names the `lodging_block_id` and passes four checks: the block must be `COMMITTED` (`ERR_LODGING_NOT_COMMITTED`); block and crew must belong to the same storm event (`ERR_CROSS_EVENT_LINK`); the crew's committed window must be contained in the block's window — starting no earlier than `window_start` and ending no later than `window_end` — (`ERR_WINDOW_OUTSIDE_BLOCK`); and the block must have room, meaning `rooms_allocated` plus the crew's `roster_size` stays within `room_count` (`ERR_NO_ROOMS_AVAILABLE`). Assignment sets the crew's `lodging_block_id`, adds `roster_size` to `rooms_allocated`, records the assignment fact — which crew and which window — for later cost allocation, and increments the `version` of both crew and block.

Departure settles the account. Departing moves `DEMOBILIZING` to `DEPARTED`, stamps `departed_at`, and computes `engagement_cost_cents`. The crew's daily cost is its `daily_rate_cents` plus `roster_size` times `per_diem_cents`; billing starts at the later of `committed_window_start` and `arrived_at`; and actual days are the elapsed time from that billing start to `departed_at` rounded up to whole twenty-four-hour days, with a floor of one day billed even when no time has elapsed — exactly twenty-four hours counts as one day, while twenty-four hours and one minute counts as two. When the departure carries a `departure_reason` of `COMPLETED`, or the crew departs at or after `committed_window_end`, the engagement cost is the actual days times the daily cost with no penalty. An early release — `departure_reason` of `EARLY_RELEASE` with departure before `committed_window_end` — adds a penalty: the remaining time to `committed_window_end`, rounded up to whole days the same way, multiplied by the daily rate and by twenty-five percent, with the product rounded half up to whole cents; per-diem is never paid on the penalty, and rounding is applied only at this final penalty step. Departure then posts a `LABOR_MUTUAL_AID` ledger entry for the actual-days portion against the crew's `service_county_code` and, when the penalty is positive, a separate `MUTUAL_AID_PENALTY` entry — which is FEMA-ineligible — and recomputes the event's `total_mutual_aid_cents`, `total_labor_cents`, `total_event_cost_cents`, and `om_cost_cents`.

Releasing a block closes the hotel account. It requires `rooms_allocated` to be zero — no crew currently assigned, otherwise `ERR_LODGING_HAS_ACTIVE_CREWS` — and moves the block from `COMMITTED` to `RELEASED`. Release posts the lodging charges as a waterfall. The block's night count is its whole number of twenty-four-hour nights, and its total is `room_count` times the night count times `nightly_rate_cents` times one plus a seven percent lodging tax, rounded half up to whole cents. Then, for every mutual-aid crew that held an assignment to the block at any point during the block's life — the facts recorded at assignment time — in the order those assignments were created, earliest first: the crew's billable nights are the overlap between its committed window and the block window — the earlier of the two window ends minus the later of the two window starts, in whole days with any partial day discarded — and its share is `roster_size` times those nights times `nightly_rate_cents` times the taxed 1.07 factor, rounded half up to whole cents before any summation, posted as a `LODGING` entry against the block's county. The tax is applied per crew share and rounded before the shares are summed; the block total is rounded separately. Whatever remains — the block total minus the sum of the shares — posts as one final overhead `LODGING` entry, deliberately absorbing the sub-cent rounding drift: a five-room block for a single night at 12,345 cents per room totals 66,046 cents, and two crews of roster sizes two and three assigned for that night post shares of 26,418 and 39,627 cents, leaving a one-cent residual on the overhead entry. Release finishes by recomputing the event's `total_lodging_cents` and `total_event_cost_cents`.

### 3.8. Materials and the Cost Ledger in Motion

Warehouses hold the storm's spare hardware. A `MaterialsManager` registers a stock pool with a `warehouse_code`, a `material_sku`, a `quantity_on_hand` of at least zero, and a `unit_cost_cents` of at least zero; the pair of warehouse and SKU must be unique, and a duplicate registration is rejected with `ERR_DUPLICATE_STOCK` (409). Two quantities are derived continuously: `quantity_reserved`, the sum of `quantity` over the pool's requisitions currently in `STAGED`, and `quantity_available`, simply `quantity_on_hand` minus `quantity_reserved`.

A requisition is opened against a work order with the `work_order_id`, the `material_stock_id` to draw from, and a `quantity` of at least one; the work order must be `READY`, `DISPATCHED`, or `IN_PROGRESS` at the time. The requisition starts in `REQUESTED`. Staging reserves the material: it requires `quantity_available` to be at least the requested `quantity` — equality is allowed, a shortfall is rejected with `ERR_INSUFFICIENT_MATERIAL` — and adds the quantity to the pool's `quantity_reserved`, incrementing the `version` of both requisition and stock. Issuing moves `STAGED` to `ISSUED`, subtracts the quantity from both `quantity_reserved` and `quantity_on_hand`, and posts a `MATERIAL` ledger entry for the quantity times the stock's `unit_cost_cents`, attributed to the county of the work order's outage's feeder and classified per §2.10. Returning an `ISSUED` requisition moves it to `RETURNED`, adds the quantity back to `quantity_on_hand`, and posts a reversal `MATERIAL` entry whose amount is the negation of the original issue amount with `reversed_entry_id` referencing the issue entry. Consuming instead moves `ISSUED` to `CONSUMED`, terminal, and lets the cost stand. A requisition in `REQUESTED` or `STAGED` may be cancelled to `CANCELLED`; cancelling a `STAGED` one subtracts its quantity from `quantity_reserved`. Work-order cancellation and outage merges drive the same cancellation cascade automatically. Issue and return each recompute the event's `total_material_cents` and `total_event_cost_cents`. The requisition list filters by `work_order_id`, `material_stock_id`, or `requisition_status`.

The ledger itself is read-only to clients. Entries can be fetched individually or listed with filters on `storm_event_id`, `work_order_id`, `entry_type`, `county_code`, or `reversed_entry_id`, and the list is ordered by `posted_at` ascending with `created_at` ascending as the tie-break. Every posting — original or reversal — immediately recomputes the seven event totals defined in §2.10, and the event's cost-summary read exposes exactly those seven figures: `total_labor_cents`, `total_material_cents`, `total_mutual_aid_cents`, `total_lodging_cents`, `total_event_cost_cents`, `capital_cost_cents`, and `om_cost_cents`.

### 3.9. Demobilization, Closure, and FEMA Recovery

An event winds down in two deliberate steps. Beginning demobilization moves `ACTIVE` to `DEMOBILIZING` and is refused with `ERR_EVENT_HAS_OPEN_WORK` while any of four kinds of open work remains: any outage of the event not yet in `VERIFIED` or `CANCELLED`; any mutual-aid crew engaged for the event not yet in `DEPARTED` or `CANCELLED`; any material requisition belonging to a work order of the event's outages not yet in `CONSUMED`, `RETURNED`, or `CANCELLED`; or any lodging block for the event not yet `RELEASED`. Closing then moves `DEMOBILIZING` to `CLOSED` and is refused with `ERR_EVENT_HAS_OPEN_WORK` while any switching order on any work order of the event's outages remains in `DRAFT`, `ISSUED`, or `APPROVED`. Once an event is `CLOSED`, the event-scoped mutations rejected with `ERR_EVENT_CLOSED` are: outage creation, confirmation, cancellation, merge, restoration report, verification, and ETR revision publication; damage-assessment creation and acceptance; work-order creation, readying, assignment, start, completion, verification, and cancellation; switching-order creation and execution; mutual-aid engagement, arrival, lodging assignment, and departure; lodging-block creation, commitment, and release; requisition creation, staging, issue, and return; and FEMA-claim creation. Certain record-keeping transitions do not check for closure and remain available against a closed event: damage-assessment submission and return, work-order arrival, switching-order issuance, approval, and abortion, mutual-aid demobilization and cancellation, requisition consumption and cancellation, the dispatch selector, and the FEMA claim lifecycle from submission onward — submission explicitly admits a `CLOSED` event.

Federal cost recovery runs per county. A `ClaimsOfficer` opens a FEMA claim with the `storm_event_id`, the `county_code` the claim covers, and the county's per-capita `threshold_cents`, at least zero; the claim starts in `DRAFT`. While in `DRAFT`, `eligible_cost_cents` is recomputed live on every read: it sums the `amount_cents` of the event's ledger entries attributed to the claim's county, counting only `LABOR_INTERNAL`, `LABOR_MUTUAL_AID`, and `MATERIAL` entries — `LODGING` and `MUTUAL_AID_PENALTY` are ineligible and excluded — and only entries whose `posted_at` falls no earlier than the event's `activated_at` and no later than ninety-six hours after it, both ends inclusive; reversal entries net against their originals inside the sum.

Submission moves `DRAFT` to `SUBMITTED` and is gated by posture and money: the event must be in `DEMOBILIZING` or `CLOSED` (`ERR_EVENT_NOT_DEMOBILIZING`), and the current `eligible_cost_cents` must be at least `threshold_cents` — equality qualifies, and a shortfall is rejected with `ERR_FEMA_THRESHOLD_NOT_MET`. Submission freezes the eligible amount into `eligible_snapshot_cents` and records the submitting officer in `preparer_user_id`. From then on, `variance_cents` reports the live eligible amount minus the frozen snapshot — it stays null while a claim is in `DRAFT` — so post-submission ledger movement is always visible against the number the county was promised.

Certification moves `SUBMITTED` to `CERTIFIED` and must be performed by a different `ClaimsOfficer` than the preparer: a matching `X-User-ID` is rejected with `ERR_SEGREGATION_OF_DUTIES`, and the certifier is recorded in `certifier_user_id`. A claim can also be pulled back: withdrawal with the optional `permanent` flag absent or false moves `SUBMITTED` back to `DRAFT` — a revision loop that clears `preparer_user_id` and `eligible_snapshot_cents` for a fresh submission — while withdrawal with `permanent` set true moves a claim from `DRAFT` or `SUBMITTED` to `WITHDRAWN`, terminal. The regulator completes the cycle: obligating moves `CERTIFIED` to `OBLIGATED`, and marking paid moves `OBLIGATED` to `PAID`, terminal. The claim list filters by `storm_event_id` or `claim_status`.

## 4. Endpoint Definitions

Operations that create a new resource — a storm event, feeder, priority customer, trouble signal, outage, ETR revision, damage assessment, crew, mutual-aid crew, lodging block, work order, switching order, stock pool, requisition, or FEMA claim — return `201 Created`. Operations that act on an existing resource, including state transitions, assignment and selector operations, and the clock adjustment, return `200 OK`. Request payloads, computed fields, and side effects for each operation are specified in §2 and §3; the table below is the index, not the specification.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/om/_clock/set_current_utc` | Set the server logical clock; sweeps expired certifications | EmergencyDirector |
| POST | `/om/storm-events` | Declare a storm event (starts DECLARED) | EmergencyDirector |
| GET | `/om/storm-events` | List storm events, filterable by event_status; paginated | All authenticated roles |
| GET | `/om/storm-events/{id}` | Get one storm event including computed cost rollups | All authenticated roles |
| POST | `/om/storm-events/{id}/activate` | DECLARED → ACTIVE; sets activated_at | EmergencyDirector |
| POST | `/om/storm-events/{id}/begin_demobilization` | ACTIVE → DEMOBILIZING; requires no open outages, crews, requisitions, or blocks | EmergencyDirector |
| POST | `/om/storm-events/{id}/close` | DEMOBILIZING → CLOSED; requires no non-terminal switching orders | EmergencyDirector |
| POST | `/om/storm-events/{id}/run_clustering` | Evaluate the anchored UNCLUSTERED signal group for a feeder; requires ACTIVE | Dispatcher |
| POST | `/om/storm-events/{id}/dispatch_next` | Assign an AVAILABLE crew to the top-ranked eligible READY work order | Dispatcher |
| GET | `/om/storm-events/{id}/cost-summary` | Computed read of the event cost rollup | All authenticated roles |
| POST | `/om/feeders` | Register a feeder (cluster thresholds default to 3 last-gasps / 5 calls) | EmergencyDirector |
| GET | `/om/feeders/{id}` | Get one feeder | All authenticated roles |
| POST | `/om/priority-customers` | Register a priority customer (starts REGISTERED) | Dispatcher |
| GET | `/om/priority-customers/{id}` | Get one priority customer | All authenticated roles |
| GET | `/om/priority-customers` | List priority customers, filterable | All authenticated roles |
| POST | `/om/priority-customers/{id}/certify` | REGISTERED or SUSPENDED → CERTIFIED; certified_through must be after logical now | Dispatcher |
| POST | `/om/priority-customers/{id}/decertify` | Any non-terminal state → DECERTIFIED (terminal) | Dispatcher |
| POST | `/om/trouble-signals` | Ingest a telemetry/call signal; restore pings require outage_id | TelemetryGateway |
| GET | `/om/trouble-signals/{id}` | Get one signal | All authenticated roles |
| GET | `/om/trouble-signals` | List signals, filterable | All authenticated roles |
| POST | `/om/outages` | Manually create a SUSPECTED outage; parent_outage_id nests | Dispatcher |
| GET | `/om/outages/{id}` | Get one outage (current_etr, etr_missed, priority_score computed) | All authenticated roles |
| GET | `/om/outages` | List outages, filterable | All authenticated roles |
| POST | `/om/outages/{id}/confirm` | SUSPECTED → CONFIRMED; creates INITIAL revision (provisional ETR) | Dispatcher |
| POST | `/om/outages/{id}/cancel` | SUSPECTED/CONFIRMED → CANCELLED (false alarm); signals DISMISSED | Dispatcher |
| POST | `/om/outages/{id}/merge` | Merge duplicate into target_outage_id; source → CANCELLED | Dispatcher |
| POST | `/om/outages/{id}/report_restored` | WORKING → RESTORED; all work orders terminal, one completed | Dispatcher |
| POST | `/om/outages/{id}/verify` | RESTORED → VERIFIED; children, work verification, restore ping gates | Dispatcher |
| GET | `/om/outages/{id}/etr-revisions` | List an outage's ETR revisions by revision_seq ascending | All authenticated roles |
| POST | `/om/outages/{id}/etr-revisions` | Publish a manual ETR revision (OCC on expected_outage_version) | Dispatcher |
| GET | `/om/outages/{id}/damage-assessments` | List an outage's damage assessments, created_at ascending | All authenticated roles |
| POST | `/om/damage-assessments` | Create a DRAFT assessment; assessor_crew_id from caller's crew | FieldCrewLead |
| GET | `/om/damage-assessments/{id}` | Get one damage assessment | All authenticated roles |
| GET | `/om/damage-assessments` | List damage assessments, filterable | All authenticated roles |
| POST | `/om/damage-assessments/{id}/submit` | DRAFT → SUBMITTED; only the assessing crew | FieldCrewLead |
| POST | `/om/damage-assessments/{id}/return` | SUBMITTED → DRAFT (rework loop) | Dispatcher |
| POST | `/om/damage-assessments/{id}/accept` | SUBMITTED → ACCEPTED (OCC); supersedes prior, posts DAMAGE_FOUND revision | Dispatcher |
| POST | `/om/crews` | Register an internal crew (starts OFF_DUTY) | Dispatcher |
| GET | `/om/crews/{id}` | Get one crew (worked_minutes_this_shift computed) | All authenticated roles |
| POST | `/om/crews/{id}/start_shift` | OFF_DUTY → AVAILABLE; resets the fatigue baseline | Dispatcher |
| POST | `/om/crews/{id}/end_shift` | AVAILABLE → OFF_DUTY; rejected while EN_ROUTE/ON_SITE | Dispatcher |
| POST | `/om/mutual-aid-crews` | Engage a mutual-aid crew for an event (starts REQUESTED) | MutualAidCoordinator |
| GET | `/om/mutual-aid-crews/{id}` | Get one mutual-aid crew | All authenticated roles |
| GET | `/om/mutual-aid-crews` | List mutual-aid crews, filterable | All authenticated roles |
| POST | `/om/mutual-aid-crews/{id}/mark_arrived` | REQUESTED → AVAILABLE inside the committed window; event ACTIVE | MutualAidCoordinator |
| POST | `/om/mutual-aid-crews/{id}/assign_lodging` | Assign the crew to a COMMITTED block on the same event | MutualAidCoordinator |
| POST | `/om/mutual-aid-crews/{id}/demobilize` | AVAILABLE → DEMOBILIZING; releases lodging; no in-flight work | MutualAidCoordinator |
| POST | `/om/mutual-aid-crews/{id}/depart` | DEMOBILIZING → DEPARTED; settles engagement cost and penalty | MutualAidCoordinator |
| POST | `/om/mutual-aid-crews/{id}/cancel` | REQUESTED → CANCELLED | MutualAidCoordinator |
| POST | `/om/lodging-blocks` | Contract a hotel room block (starts OPEN); whole-night window | MutualAidCoordinator |
| GET | `/om/lodging-blocks/{id}` | Get one lodging block (rooms_allocated computed) | All authenticated roles |
| GET | `/om/lodging-blocks` | List lodging blocks, filterable | All authenticated roles |
| POST | `/om/lodging-blocks/{id}/commit` | OPEN → COMMITTED (assignable) | MutualAidCoordinator |
| POST | `/om/lodging-blocks/{id}/release` | COMMITTED → RELEASED; posts per-crew lodging entries plus residual | MutualAidCoordinator |
| POST | `/om/work-orders` | Create a work order on an outage (CREATED / PENDING_VERIFY) | Dispatcher |
| GET | `/om/work-orders/{id}` | Get one work order | All authenticated roles |
| GET | `/om/work-orders` | List work orders, filterable | All authenticated roles |
| POST | `/om/work-orders/{id}/ready` | CREATED → READY; non-ASSESSMENT work needs an ACCEPTED assessment | Dispatcher |
| POST | `/om/work-orders/{id}/assign` | READY → DISPATCHED to exactly one internal or mutual-aid crew | Dispatcher |
| POST | `/om/work-orders/{id}/arrive` | Mark the assigned crew on site; EN_ROUTE → ON_SITE | FieldCrewLead, Dispatcher |
| POST | `/om/work-orders/{id}/start` | DISPATCHED → IN_PROGRESS; on-site and switching gates | FieldCrewLead, Dispatcher |
| POST | `/om/work-orders/{id}/complete` | IN_PROGRESS → COMPLETED; crew release and labor posting | FieldCrewLead, Dispatcher |
| POST | `/om/work-orders/{id}/verify` | PENDING_VERIFY → VERIFY_PASSED or VERIFY_FAILED (reopens execution) | Dispatcher |
| POST | `/om/work-orders/{id}/cancel` | CREATED/READY/DISPATCHED → CANCELLED; releases crew and requisitions | Dispatcher |
| POST | `/om/switching-orders` | Create a DRAFT switching order for a non-terminal work order | SystemOperator |
| GET | `/om/switching-orders/{id}` | Get one switching order | All authenticated roles |
| GET | `/om/switching-orders` | List switching orders, filterable | All authenticated roles |
| POST | `/om/switching-orders/{id}/issue` | DRAFT → ISSUED; only the issuer | SystemOperator |
| POST | `/om/switching-orders/{id}/approve` | ISSUED → APPROVED; approver must differ from issuer | SystemOperator |
| POST | `/om/switching-orders/{id}/execute` | APPROVED → EXECUTED; work order non-terminal and event ACTIVE | SystemOperator |
| POST | `/om/switching-orders/{id}/abort` | DRAFT/ISSUED/APPROVED → ABORTED; clears the work order's link | SystemOperator |
| POST | `/om/material-stocks` | Register a stock pool; (warehouse_code, material_sku) unique | MaterialsManager |
| GET | `/om/material-stocks/{id}` | Get one stock pool (reserved/available computed) | All authenticated roles |
| POST | `/om/material-requisitions` | Create a REQUESTED requisition for an in-flight work order | MaterialsManager |
| GET | `/om/material-requisitions/{id}` | Get one requisition | All authenticated roles |
| GET | `/om/material-requisitions` | List requisitions, filterable | All authenticated roles |
| POST | `/om/material-requisitions/{id}/stage` | REQUESTED → STAGED; reserves quantity | MaterialsManager |
| POST | `/om/material-requisitions/{id}/issue` | STAGED → ISSUED; decrements stock and posts MATERIAL entry | MaterialsManager |
| POST | `/om/material-requisitions/{id}/return` | ISSUED → RETURNED; restores stock with a reversal entry | MaterialsManager |
| POST | `/om/material-requisitions/{id}/consume` | ISSUED → CONSUMED (terminal; cost stands) | MaterialsManager |
| POST | `/om/material-requisitions/{id}/cancel` | REQUESTED/STAGED → CANCELLED; STAGED releases its reservation | MaterialsManager |
| GET | `/om/cost-ledger-entries/{id}` | Get one ledger entry | All authenticated roles |
| GET | `/om/cost-ledger-entries` | List ledger entries, filterable; posted_at then created_at ascending | All authenticated roles |
| POST | `/om/fema-claims` | Open a DRAFT FEMA claim for an event and county | ClaimsOfficer |
| GET | `/om/fema-claims/{id}` | Get one claim (eligible cost and variance computed) | All authenticated roles |
| GET | `/om/fema-claims` | List claims, filterable | All authenticated roles |
| POST | `/om/fema-claims/{id}/submit` | DRAFT → SUBMITTED; freezes the eligibility snapshot | ClaimsOfficer |
| POST | `/om/fema-claims/{id}/certify` | SUBMITTED → CERTIFIED; certifier must differ from preparer | ClaimsOfficer |
| POST | `/om/fema-claims/{id}/withdraw` | SUBMITTED → DRAFT, or DRAFT/SUBMITTED → WITHDRAWN when permanent | ClaimsOfficer |
| POST | `/om/fema-claims/{id}/obligate` | CERTIFIED → OBLIGATED | Regulator |
| POST | `/om/fema-claims/{id}/mark_paid` | OBLIGATED → PAID (terminal) | Regulator |

## 5. Error Code Catalogue

Trigger conditions for each error are specified where the guarded workflow is described in §2 and §3; this table is the identifier index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_ASSIGNEE_AMBIGUOUS` | 400 Bad Request |
| `ERR_INVALID_STATE_TRANSITION` | 400 Bad Request |
| `ERR_EVENT_NOT_ACTIVE` | 400 Bad Request |
| `ERR_EVENT_NOT_DEMOBILIZING` | 400 Bad Request |
| `ERR_EVENT_CLOSED` | 400 Bad Request |
| `ERR_EVENT_HAS_OPEN_WORK` | 400 Bad Request |
| `ERR_LODGING_NOT_COMMITTED` | 400 Bad Request |
| `ERR_PING_OUTAGE_STATE` | 400 Bad Request |
| `ERR_OUTAGE_WORK_OPEN` | 400 Bad Request |
| `ERR_OUTAGE_CHILDREN_OPEN` | 400 Bad Request |
| `ERR_UNVERIFIED_WORK_REMAINS` | 400 Bad Request |
| `ERR_RESTORE_PING_MISSING` | 400 Bad Request |
| `ERR_SWITCHING_NOT_EXECUTED` | 422 Unprocessable Entity |
| `ERR_FATIGUE_LIMIT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_CREW_NOT_ON_SITE` | 422 Unprocessable Entity |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_STALE_OUTAGE_VERSION` | 412 Precondition Failed |
| `ERR_CROSS_EVENT_LINK` | 422 Unprocessable Entity |
| `ERR_PARENT_OUTAGE_TERMINAL` | 422 Unprocessable Entity |
| `ERR_MERGE_CYCLE` | 422 Unprocessable Entity |
| `ERR_ASSESSMENT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_ETR_IN_PAST` | 422 Unprocessable Entity |
| `ERR_ETR_BACKWARD_FORBIDDEN` | 422 Unprocessable Entity |
| `ERR_ETR_LOCKED_HORIZON` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_ENGAGEMENT_WINDOW` | 422 Unprocessable Entity |
| `ERR_WINDOW_OUTSIDE_BLOCK` | 422 Unprocessable Entity |
| `ERR_LODGING_WINDOW_OVERLAP` | 422 Unprocessable Entity |
| `ERR_SIGNAL_IN_FUTURE` | 422 Unprocessable Entity |
| `ERR_CERTIFICATION_WINDOW_PAST` | 422 Unprocessable Entity |
| `ERR_ETR_EXTENSION_EXCEEDS_CAP` | 422 Unprocessable Entity |
| `ERR_CREW_TYPE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_CREW_NOT_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_STOCK` | 409 Conflict |
| `ERR_NO_ELIGIBLE_WORK` | 422 Unprocessable Entity |
| `ERR_NO_ROOMS_AVAILABLE` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_MATERIAL` | 422 Unprocessable Entity |
| `ERR_FEMA_THRESHOLD_NOT_MET` | 422 Unprocessable Entity |
| `ERR_LODGING_HAS_ACTIVE_CREWS` | 422 Unprocessable Entity |
