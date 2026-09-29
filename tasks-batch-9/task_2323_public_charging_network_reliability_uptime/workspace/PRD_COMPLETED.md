# Public Charging Uptime Compliance API — Product Requirements Document

## 1. Introduction

A federally funded public charging network operator lives or dies by a single number: the percentage of time its dispensers were actually able to sell electrons to a driver who pulled in. That number is not a marketing figure — it is the condition on which programme reimbursement is paid, and it is computed from a chain of evidence that starts at a remote-monitoring fault code and ends at a signed claim line item. Today that chain is assembled by hand across monitoring dashboards, technician phone calls, depot spreadsheets and email threads with the property host, and the resulting uptime figure is impossible to defend under audit.

This document specifies the API that replaces that chain with a single system of record. It governs host site agreements and their power-upgrade and parking-enforcement obligations; station commissioning against connector-count, capacity and payment-interoperability gates; remote fault ingestion, severity classification and the dispatch of field technicians inside contractual response windows; depot spare-part encumbrance and replacement lead times; the two uptime methodologies (the operator's provisional view and the federal final view) and the excluded-outage-cause adjudication that separates them; reimbursement claims with uptime-conditioned withholds and remediation credits; and driver complaint intake with session refund handling.

Two design commitments run through every section. First, **the network hierarchy is self-consistent**: a dispenser going out of service is not an isolated fact — it suspends its station, and clearing it un-suspends the station again, automatically, without an explicit client request on the station. Second, **compliance decisions are separated from the work they judge**: the operator who dispatched a repair cannot verify that the repair worked, and the auditor who finalised an uptime report cannot decide the money claimed against it.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that hold everywhere in the API. Where §3 narrates a workflow, it does so on top of these guarantees rather than restating them.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity that user is acting in. If either header is missing or empty, or if `X-User-Role` is not one of the six declared role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the acting role is not authorised for the endpoint being called, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The six roles are `NetworkOperator`, `FieldTechnician`, `ComplianceAuditor`, `ProgramAdministrator`, `HostSiteManager`, and `CustomerSupportAgent`.

- **`NetworkOperator`** is the network's own staff: they build sites and stations, install dispensers, ingest and classify faults, dispatch maintenance, manage depot inventory, declare reporting periods, and file claims and remediations.
- **`FieldTechnician`** is a contracted maintenance technician who works only the dispatches assigned to them.
- **`ComplianceAuditor`** is the independent uptime-compliance auditor: they certify payment terminals, adjudicate outage exclusions, verify repairs, finalise reports under the federal methodology, and decide or reverse session refunds.
- **`ProgramAdministrator`** is the federal programme office: they accept or return submitted reports and adjudicate reimbursement claims.
- **`HostSiteManager`** is the property host's representative.
- **`CustomerSupportAgent`** is the driver-facing support desk.

Identity semantics differ by role, and they matter. When `X-User-Role` is `HostSiteManager`, `X-User-ID` is the `id` of the acting `HostSite`; ownership checks on any resource that references a `HostSite` compare the resource's foreign-key field to `X-User-ID`, so a `HostSiteManager` may amend only the host site whose `id` equals `X-User-ID` and any other target is rejected with `ERR_HOST_SITE_FORBIDDEN` (HTTP 403).

When `X-User-Role` is `NetworkOperator`, `FieldTechnician`, `ComplianceAuditor`, `ProgramAdministrator`, or `CustomerSupportAgent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a transition writes it — as `created_by_user_id` and `dispatch_created_by_user_id` for a dispatching `NetworkOperator`, as `finalized_by_user_id` for a finalising `ComplianceAuditor`, as `decided_by_user_id` for a deciding `ProgramAdministrator`, and as `refund_requested_by_user_id` for a `CustomerSupportAgent` filing a refund — but it never compares that value to any entity's `id`. The one comparison the server does make against an opaque identifier is `technician_user_id`: a `FieldTechnician` may only act on a dispatch whose `technician_user_id` equals their `X-User-ID`, and a mismatch yields `ERR_NOT_ASSIGNED_TECHNICIAN` (HTTP 403). That field holds an opaque operator id supplied by the dispatching operator, not an entity id.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`, followed by twenty characters drawn from the upper-case letters and the digits.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits; envelope metadata is the one place the server reads real wall-clock time rather than the logical clock of §2.4.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints only; `total_count` counts the rows matching the request's filters before the page is cut, and `has_more` is true exactly when `offset` plus the number of items on this page is still less than `total_count`.

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

### 2.3. Pagination and Collection Filters

Collection endpoints are paginated through two query parameters. `limit` is the maximum number of items returned; it defaults to 10, may not be lower than 1, and may not exceed 100. `offset` is the number of items skipped before the page begins; it defaults to 0 and may not be negative. A `limit` or `offset` outside those bounds — or one that is not parseable as an integer — is a request-shape failure and is rejected with `ERR_INVALID_REQUEST` (HTTP 400); a parameter that is absent, or supplied as an empty string, takes its default instead.

Unless a specific endpoint states otherwise, every list endpoint returns its resources sorted by `created_at` in ascending order, and rows sharing a `created_at` — routine, because the logical clock only moves when a client drives it — are ordered among themselves by the order in which the server created them. Every list response carries `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

Collections also accept domain filters, all of them optional and all of them exact-match on the named field:

- The host-site collection accepts `agreement_status`. Stations under a host site are filtered by `status`.
- Charging ports under a station are filtered by `service_state` and `maintenance_state`. Uptime reports under a station are filtered by `state`.
- Outage events under a charging port are filtered by `state` and `fault_class`.
- The maintenance-dispatch collection accepts `outage_event_id`, `port_id`, `state`, and `technician_user_id`.
- The spare-part collection accepts `part_class`. The part-reservation collection accepts `dispatch_id`, `spare_part_id`, and `state`.
- Reimbursement claims under an uptime report are filtered by `state`.
- The customer-complaint collection accepts `station_id`, `port_id`, `linked_outage_event_id`, `state`, and `refund_state`.

Reverse-reachability collections that hang off a parent resource take that parent's `id` as their path segment. These listings are deliberately complete: they include rows a creation response never returned to any client — system-generated outage events, part reservations released by a station teardown, and claims driven to `SUPERSEDED` by a later filing all appear.

### 2.4. Common Resource Properties and the Logical Clock

All ten persisted resource types — host sites, stations, charging ports, outage events, maintenance dispatches, spare parts, part reservations, uptime reports, reimbursement claims and customer complaints — carry the same four system-managed properties:

- **`id`** (string): a server-minted UUID. It carries no type prefix.
- **`created_at`** (string): an ISO 8601 UTC timestamp with three fractional second digits, recording when the resource was first created.
- **`updated_at`** (string): an ISO 8601 UTC timestamp in the same format, refreshed on every mutation of the resource.
- **`version`** (integer): a counter that increments by one on every mutation of the resource. A resource that a single request touches at several links — routine inside the cascades of §2.6, and equally so where one endpoint writes a field and then drives a state change on the same row — advances by exactly one for that request, not once per link.

No entity in this system omits `updated_at` or `version`.

Both timestamps and every `logical clock now` reference in this document read from a server-side **logical clock**, not from wall-clock time. The clock's startup value is exactly `2026-08-01T00:00:00Z`, and before the clock is ever set it reads that default rather than falling back to real time. Any of the six roles may drive the clock forward or backward through a test-driving capability that accepts a single non-optional `current_utc` instant and returns that instant as the clock's new reading, in a `data` object carrying the one field `current_utc`; every subsequent logical-clock read returns it, and driving the clock mutates no persisted resource. Making the clock explicit is what makes port eligibility inside the uptime calculation deterministic, because eligibility is decided against each port's `created_at`.

Timestamps the server stamps itself — `commissioned_at`, `retired_at`, `cleared_at`, `excluded_at`, `arrived_at`, `promised_repair_at`, `expected_available_at`, `refund_settled_at` — all read the logical clock at the moment of the transition that writes them, and all carry three fractional second digits.

### 2.5. Identifier Resolution and Request Ordering

Any request that names resources resolves them before it evaluates business rules. Identifiers embedded in the URL path are resolved **left to right**, and the first path segment that names nothing aborts the request with that segment's own 404 error. A request for the ports of a non-existent station therefore fails with `ERR_STATION_NOT_FOUND`, never with a port-level error.

Once the path resolves, foreign keys carried in the request body are resolved in this declaration order: `host_site_id`, `station_id`, `port_id`, `outage_event_id`, `dispatch_id`, `spare_part_id`, `uptime_report_id`, `complaint_id`, and finally each `port_id` inside `line_items`. The matching failures are `ERR_HOST_SITE_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_PORT_NOT_FOUND`, `ERR_OUTAGE_NOT_FOUND`, `ERR_DISPATCH_NOT_FOUND`, `ERR_SPARE_PART_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_UPTIME_REPORT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, and `ERR_COMPLAINT_NOT_FOUND`, each returned with HTTP 404.

### 2.6. Cascade Discipline Across the Network Hierarchy

The network is a four-level hierarchy — host site, station, charging port, outage event — with maintenance dispatches and part reservations hanging off the outage, and the system keeps that hierarchy consistent without waiting for a client to reconcile it. Two cascades dominate the design.

The **recovery cascade** runs upward. Completing a repair closes its outage; closing the last unresolved outage on a dispenser returns that dispenser to service; returning the last out-of-service dispenser to service lifts an automatic station suspension. Each link is a real mutation of a real resource: every entity touched has its `updated_at` refreshed and its `version` incremented by one, exactly as though a client had written to it directly.

The **teardown cascade** runs downward. Decommissioning a station retires its dispensers, excludes the open outages on those dispensers, cancels the dispatches sent against those outages, and releases the depot stock those dispatches had earmarked — four levels deep, in one request. The full link-by-link specification lives in §3.3.

An automatic suspension and an operator's deliberate suspension are deliberately distinguishable, because the recovery cascade must never quietly undo a decision a human made. The station records `suspension_source`, and only a suspension whose source is `AUTOMATIC` is eligible for automatic resumption.

### 2.7. Stale-Version Guards on Depot and Reporting Writes

Two creation operations sit on top of a parent resource whose balance the client must have read before writing, and both are guarded by optimistic concurrency control against that parent's `version`.

Filing a reimbursement claim requires a non-optional `expected_uptime_report_version` field carrying the client's last observed `version` of the `UptimeReport` named by `uptime_report_id`. If that value does not equal the report's current `version`, the request is rejected with `ERR_STALE_PARENT_VERSION` (HTTP 412). The guard exists because claim filing is a supersede pattern: a new claim drives any existing `PENDING` claim on the same report to `SUPERSEDED` and raises the report's `claim_count`, so a writer holding a stale view of the report would silently discard a claim it never saw.

Earmarking depot stock requires a non-optional `expected_spare_part_version` field carrying the client's last observed `version` of the `SparePart` named by `spare_part_id`. A value that does not equal the part's current `version` is rejected with `ERR_STALE_PARENT_VERSION` (HTTP 412). Reservation creation legitimately succeeds any number of times against the same part, so the state machine alone cannot detect that the depot balance the writer reasoned about has already moved; pinning `SparePart.version` reduces that to a stale-version check.

No other endpoint in this API accepts a version field, and no other endpoint performs a version check.

### 2.8. Segregation of Duties in Compliance Decisions

Two independence rules are enforced structurally, both rejecting with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409).

**SoD-1 — repair verification.** When a `NetworkOperator` creates a maintenance dispatch, their `X-User-ID` is copied onto the outage as `dispatch_created_by_user_id`. A `ComplianceAuditor` verifying that outage's resolution must present an `X-User-ID` different from that recorded value.

**SoD-2 — claim adjudication.** When a `ComplianceAuditor` finalises an uptime report, their `X-User-ID` is stored as `finalized_by_user_id`. Whoever later decides a reimbursement claim drawn on that report must present an `X-User-ID` different from that recorded value — the bar follows the person, not the role, so it applies even when the same human acts as `ProgramAdministrator`. Returning a submitted report clears `finalized_by_user_id` back to null, which releases the bar until a new auditor finalises it.

### 2.9. Numeric Precision, Minute Arithmetic and Rounding

Money in this system is always whole cents held in integer fields — `amount_cents` on a claim line item, `requested_amount_cents`, `withheld_amount_cents`, `approved_amount_cents`, `session_price_per_kwh_cents`, `session_idle_fee_cents`, `session_charged_cents`, `refund_amount_cents`, `retained_amount_cents`, and `refund_liability_cents`. Where a monetary figure is derived from a non-integer product, the product is rounded half up to a whole cent.

Percentages and power figures carry exactly two decimal places and are rounded half up, and every such figure is serialised as a JSON number rather than a string, so the JSON text of a rounded value does not preserve its trailing zeros: `uptime_pct`, `payment_interop_score`, `effective_uptime_pct`, `remediation_credit_pp`, `withhold_rate`, `installed_power_kw`, `rated_power_kw`, and `committed_service_capacity_kw`. Delivered energy, `session_energy_kwh`, carries three decimal places.

Every duration figure in the system is a whole number of minutes. When a duration is derived from two instants, the elapsed seconds are divided by sixty and the result is rounded **down** to a whole minute; a partial minute is never counted. This applies to `period_minutes`, to each outage's overlap contribution inside a reporting period, to each outage's closed duration in the station downtime ledger, and to `total_hold_minutes`. The one exception is the expedite discount inside the parts-hold promise, which rounds **up**; §3.6 says so where the rule lives.

### 2.10. Interval Conventions

Two different interval conventions coexist in this API, and confusing them is the most common source of wrong overlap decisions.

**Maintenance windows are half-open.** A dispatch window runs from `window_start_at` inclusive to `window_end_at` exclusive. Two windows on the same dispenser that merely touch at an endpoint — the new window starting exactly when an existing one ends, or ending exactly when an existing one starts — do **not** overlap and are both permitted. The same half-open convention governs whether an outage's downtime window intersects a disputed charging session: an outage window runs from `detected_at` inclusive up to `cleared_at` exclusive (or forward without bound while `cleared_at` is null), a session runs from `session_started_at` inclusive to `session_ended_at` exclusive, and a zero-length touch between them is not an overlap.

**Reporting periods are closed on both ends.** An uptime report's period runs from `period_start` inclusive through `period_end` inclusive. Because both endpoints are inclusive, an *adjacent* period on the same station — one whose `period_start` equals an existing period's `period_end`, or whose `period_end` equals an existing period's `period_start` — **is** an overlap and is rejected.

### 2.11. Validation Precedence

When several rules could reject the same request, they are evaluated in a fixed order so that the error the client sees is always the most fundamental one. The order is:

1. Header authentication — `ERR_UNAUTHENTICATED`. Applies to every endpoint.
2. Role authorisation against the endpoint's permitted roles — `ERR_UNAUTHORIZED`. Applies to every endpoint. Where an endpoint admits two roles but reserves each of its legs to one of them — the `DRAFT` station revert, the exclusion `REQUEST`, the resolution `VERIFY`, the reservation `CONSUME` and the ledger `SETTLE`, each against its counterpart legs — the leg's own role restriction is also `ERR_UNAUTHORIZED`, and because the leg is named in the request body it is enforced only after step 5 has validated that sub-selector.
3. Existence of every identifier, path first (left to right) then body foreign keys in declaration order — the 404 family listed in §2.5. Applies to every endpoint.
4. Host-site ownership: a `HostSiteManager` may act only on the host site whose `id` equals `X-User-ID` — `ERR_HOST_SITE_FORBIDDEN`. Applies to host site amendment.
5. Request-body shape: every required field present, every enum value inside its declared set, every integer and number inside its declared range, `line_items` an array of well-formed objects, and `limit`/`offset` inside their declared bounds — `ERR_INVALID_REQUEST`. Applies to every endpoint. A `line_items` array that is present but empty also fails at this position, ahead of the stale-version guard of step 7, but with `ERR_CLAIM_LINE_ITEMS_EMPTY` rather than `ERR_INVALID_REQUEST`. Body fields and query parameters an endpoint does not declare are ignored rather than rejected, and a field sent explicitly as `null` counts as absent.
6. Natural-key uniqueness for `site_code`, `station_code`, `dispenser_serial` and `part_number` — `ERR_SITE_CODE_DUPLICATE`, `ERR_STATION_CODE_DUPLICATE`, `ERR_DISPENSER_SERIAL_DUPLICATE`, `ERR_PART_NUMBER_DUPLICATE`. Applies to the four corresponding creation operations: host site, station, charging port, spare part.
7. The stale-version guard of §2.7 — `ERR_STALE_PARENT_VERSION`. Applies to exactly two operations: claim filing and part-reservation creation.
8. Transition legality: the target resource occupies a state from which the requested transition exists in the relevant dimension, including the cross-dimension guard that a refund request requires the complaint's intake dimension to be `TRIAGED`, and including the sub-selector carried in the body for exclusion actions, progress events and reservation dispositions — `ERR_INVALID_STATE`. Applies to every state-changing endpoint.
9. Terminality: the target resource is not already in a terminal state for the dimension being changed — `ERR_ALREADY_TERMINAL`. Applies to station status transitions, dispenser retirement, claim review, and complaint closure.
10. Segregation of duties, both SoD-1 and SoD-2 — `ERR_SEGREGATION_OF_DUTIES`. Applies to outage resolution reviews and claim decisions.
11. Technician certification coverage — `ERR_TECHNICIAN_NOT_CERTIFIED`. Applies to dispatch creation.
12. Technician assignment: only the assigned technician may act — `ERR_NOT_ASSIGNED_TECHNICIAN`. Applies to four operations: dispatch progress events, parts holds, dispatch completion, and the `CONSUME` reservation disposition.
13. Cross-entity ownership — `ERR_OUTAGE_PORT_MISMATCH`, `ERR_CLAIM_LINE_PORT_MISMATCH`, `ERR_COMPLAINT_PORT_MISMATCH`, `ERR_COMPLAINT_OUTAGE_MISMATCH`. Applies to four operations: dispatch creation, claim filing, complaint intake, and complaint triage.
14. Interval well-formedness — `ERR_DETECTED_AT_IN_FUTURE`, `ERR_DETECTED_AT_BEFORE_PORT`, `ERR_DISPATCH_WINDOW_INVALID`, `ERR_REPORTING_PERIOD_INVALID`, `ERR_REPORTING_PERIOD_NOT_ELAPSED`, `ERR_SESSION_WINDOW_INVALID`. Applies to four creation operations: outage ingestion, dispatch creation, reporting-period declaration, and complaint intake.
15. Half-open window overlap on the dispenser — `ERR_DISPATCH_WINDOW_OVERLAP`. Applies to dispatch creation.
16. Closed-period overlap on the station — `ERR_REPORTING_PERIOD_OVERLAP`. Applies to reporting-period declaration.
17. Access-window well-formedness — `ERR_INVALID_ACCESS_WINDOW`. Applies to host site registration and host site amendment.
18. The commissioning gate ladder, itself evaluated in the order given in §3.3 — `ERR_HOST_AGREEMENT_NOT_EXECUTED`, `ERR_POWER_UPGRADE_NOT_ENERGIZED`, `ERR_PARKING_ENFORCEMENT_REQUIRED`, `ERR_PORT_COUNT_BELOW_DECLARED`, `ERR_SITE_CAPACITY_EXCEEDED`. Applies to commissioning.
19. The interoperability score threshold, evaluated after the whole ladder above — `ERR_INTEROP_SCORE_BELOW_THRESHOLD`. Applies to commissioning.
20. Exclusion eligibility — `ERR_EXCLUSION_CAUSE_NOT_ELIGIBLE`. Applies to exclusion actions, and on an exclusion `REQUEST` it is evaluated *after* the dispenser-retirement check that step 21 names, not before it.
21. Cross-entity state dependency — `ERR_UPTIME_REPORT_NOT_ACCEPTED` on claim review, `ERR_STATION_NOT_SERVICEABLE` on the `EN_ROUTE` dispatch progress event, and `ERR_PORT_RETIRED` on outage classification, on the `REOPEN` leg of a resolution review and on the `REQUEST` leg of an exclusion action. The auditor's legs — `VERIFY`, and the `APPROVE`, `REJECT` and `REVOKE` exclusion actions — do not test the dispenser for retirement at all.
22. No attributed outage awaiting exclusion adjudication — `ERR_EXCLUSION_REVIEW_PENDING`. Applies to report finalisation.
23. A non-zero reporting denominator — `ERR_NO_REPORTABLE_PORT_MINUTES`. Applies to both provisional computation and finalisation.
24. Refund basis eligibility — `ERR_REFUND_BASIS_NOT_ELIGIBLE`. Applies to refund requests.
25. No in-flight refund at closure — `ERR_REFUND_IN_FLIGHT`. Applies to complaint closure.
26. Reservation quantity and release validity — `ERR_RESERVATION_QTY_INVALID`. Applies to reservation creation and reservation disposition.
27. The withhold tier matching the requested decision — `ERR_UPTIME_BELOW_APPROVAL_THRESHOLD`, `ERR_WITHHOLD_RATE_MISMATCH`. Applies to claim decisions; the companion `ERR_CLAIM_LINE_ITEMS_EMPTY` of claim filing is raised at step 5, as noted there, rather than at this position.
28. Session money bounds — `ERR_REFUND_EXCEEDS_SESSION_CHARGE`, `ERR_SESSION_CHARGE_INVALID`. Applies to complaint intake and refund decisions.

## 3. Business Logic & Workflows

### 3.1. Host Site Agreements, Power Upgrades and Access Governance

Everything begins with the property. A `NetworkOperator` registers a **host site** — the container for the agreement with the property owner — by supplying a `site_code`, the `host_org_name` under which the property owner does business, and the `committed_service_capacity_kw` the host contracted to make available. The `site_code` must be non-empty and globally unique, compared case-sensitively; a collision is rejected with `ERR_SITE_CODE_DUPLICATE`. The `host_org_name` must be non-empty, and `committed_service_capacity_kw` must be greater than zero.

Six further attributes may be supplied at registration and each has a default. The `agreement_status` records how far the paperwork has progressed and is one of `DRAFT`, `EXECUTED`, or `TERMINATED`, defaulting to `DRAFT`. The `power_upgrade_status` tracks the utility service upgrade and is one of `NOT_REQUIRED`, `REQUESTED`, `IN_PROGRESS`, or `ENERGIZED`, defaulting to `REQUESTED`. The `access_hours_mode` is either `TWENTY_FOUR_SEVEN` or `RESTRICTED` and defaults to `TWENTY_FOUR_SEVEN`. When access is restricted, `access_open_minute` and `access_close_minute` bound the public access window as minutes of the UTC day: `access_open_minute` defaults to 0 and may run from 0 through 1439, while `access_close_minute` is treated as exclusive, defaults to 1440, and may run from 1 through 1440. Finally, `parking_enforcement_mode` describes the contracted level of anti-blocking enforcement and is one of `NONE`, `SIGNAGE_ONLY`, or `TOWING_ENFORCED`, defaulting to `NONE`.

Whenever `access_hours_mode` is `RESTRICTED`, the opening minute must be strictly earlier than the closing minute; if it is not, the request fails with `ERR_INVALID_ACCESS_WINDOW`. This rule is checked both when the site is registered and every time it is amended, and on an amendment it is evaluated against the *merged* result — each of the three fields the amendment omits contributes the value already stored on the site.

Each site also exposes a computed `station_count`: the number of stations installed at that site whose lifecycle state is anything other than `DECOMMISSIONED`. It starts at zero, rises by one each time a station is created there, and falls by one when a station is decommissioned; because the figure is derived rather than stored, neither event is a mutation of the host site — its `updated_at` and `version` are left untouched by both.

Amending the agreement is the only path by which any of these attributes change — no other operation in the system moves `agreement_status`, `power_upgrade_status`, `access_hours_mode`, `access_open_minute`, `access_close_minute`, `parking_enforcement_mode`, or `committed_service_capacity_kw`. An amendment may carry any subset of those seven fields — including the empty subset, which changes nothing yet still counts as a mutation — is available to a `NetworkOperator` for any site and to a `HostSiteManager` only for the site whose `id` matches their `X-User-ID`, and increments the host site's `version`. No `agreement_status` blocks it: a site sitting at `TERMINATED` is amendable like any other. One consequence deserves emphasis: amending a site's access hours does **not** retroactively move any `response_deadline_at` that has already been computed for a dispatch. Deadlines are pinned at dispatch creation.

### 3.2. Stations, Dispensers and the Interoperability Score

A station is created by a `NetworkOperator` against a payload naming the `host_site_id` it is installed at, a globally unique `station_code` (a collision yields `ERR_STATION_CODE_DUPLICATE`), the `power_class` of its dispensers — one of `L2_19`, `DCFC_150`, or `DCFC_350` — and the `declared_port_count`, the connector count the station was awarded funding for, which must be at least 1. An optional `corridor_designated` flag, defaulting to false, marks a station sitting on a federally designated alternative fuel corridor; it tightens maintenance response later. A new station opens in `DRAFT` with `suspension_source` set to `NONE` and `commissioned_at` null, and its creation raises the host site's station count.

Alongside its lifecycle fields a station carries a bank of derived figures, all readable and none directly writable: `commissioned_port_count` (dispensers on the station that are not retired), `out_of_service_port_count` (dispensers currently out of service), `installed_power_kw` (the sum of `rated_power_kw` across the station's non-retired dispensers, to two decimals), `payment_interop_score`, the three-part downtime ledger `gross_downtime_minutes_lifetime` / `excluded_downtime_minutes_lifetime` / `billable_downtime_minutes_lifetime`, and `refund_liability_cents` (the sum of `refund_amount_cents` over the station's complaints whose refund has settled). All of them begin at zero.

**Installing a dispenser.** A `NetworkOperator` adds a charging port by naming its `station_id`, its `connector_type` — one of `CCS1`, `NACS`, `CHADEMO`, or `J1772` — its nameplate `rated_power_kw` (greater than zero, two decimals), a globally unique `dispenser_serial` for the cabinet (a collision yields `ERR_DISPENSER_SERIAL_DUPLICATE`), and the non-empty `terminal_model` of the payment terminal bolted to it. Four interoperability attributes are optional at install time and all default to their least-capable value: `contactless_enabled` (false) records whether the terminal takes contactless bank cards; `plug_and_charge_enabled` (false) records ISO 15118 Plug and Charge; `price_display_verified` (false) records that the per-kWh price display has been field-verified; and `roaming_ocpi_version` (`NONE`) records the OCPI version the port's session records are published to roaming partners with, chosen from `NONE`, `V2_1_1`, `V2_2_1`, or `V2_3_0`. Only `V2_2_1` and `V2_3_0` count as roaming-compliant. A newly installed dispenser starts with `terminal_certification_status` of `PENDING`, a `service_state` of `IN_SERVICE`, a `maintenance_state` of `NONE`, and `retired_at` null; installing it recomputes the station's non-retired port count, `installed_power_kw`, and `payment_interop_score`.

The four interoperability attributes remain amendable afterwards by a `NetworkOperator` — an amendment may carry any subset of `contactless_enabled`, `plug_and_charge_enabled`, `price_display_verified`, and `roaming_ocpi_version`, the empty subset included — and each amendment recomputes the station's `payment_interop_score` and increments the dispenser's `version`. Neither of the dispenser's own dimensions gates the amendment: a `RETIRED` dispenser may still be amended, it simply no longer counts in the score.

**The interoperability score.** `payment_interop_score` is a weighted percentage over the station's *scored* dispensers, which are exactly those whose `service_state` is `IN_SERVICE` or `OUT_OF_SERVICE`. If the station has no scored dispensers at all, the score is `0.00` and no further arithmetic runs. Otherwise the server computes four shares, each the count of scored dispensers satisfying a condition divided by the total number of scored dispensers: the contactless share counts dispensers whose `contactless_enabled` is true; the Plug-and-Charge share counts dispensers whose `plug_and_charge_enabled` is true; the price-display share counts dispensers whose `price_display_verified` is true; and the roaming share counts dispensers that are both certified — `terminal_certification_status` equal to `CERTIFIED` — and publishing at `V2_2_1` or `V2_3_0`. The four shares are left as exact fractions and are never individually rounded. The score is one hundred multiplied by the weighted sum of those four shares, weighting contactless at forty percent and each of Plug-and-Charge, price display and roaming at twenty percent, and that single product is rounded half up to two decimal places. Because retired dispensers leave both the numerator and the denominator, retiring a non-compliant dispenser *raises* the score.

The score is recomputed whenever the scored population or its attributes could have moved: on dispenser installation, on interoperability amendment, on a terminal-certification outcome, on dispenser retirement, at the start of commissioning, and during a station teardown.

**Terminal certification.** Only a `ComplianceAuditor` records the payment-terminal outcome, supplying a `certification_status` of either `CERTIFIED` or `REVOKED`. Either outcome recomputes the station's `payment_interop_score` and increments the dispenser's `version`, and neither is gated on the dispenser's `service_state` or `maintenance_state` — a `RETIRED` dispenser may still have its terminal certified or revoked. `REVOKED` on a dispenser that is currently `IN_SERVICE` does considerably more: it drives `service_state` from `IN_SERVICE` to `OUT_OF_SERVICE`, raises the station's out-of-service count, synthesises an outage event on that dispenser with `is_system_generated` set to true, a `fault_class` of `MAJOR`, a `fault_code` of `TERMINAL_CERT_REVOKED`, and `detected_at` set to the logical clock's current reading — that synthesised row opens in `DETECTED` like any other, with `cleared_at`, `pre_exclusion_state`, `excluded_at` and `dispatch_created_by_user_id` null and `excluded_cause_claim` at `NONE` — and may drive the station from `OPERATIONAL` to `SUSPENDED` with `suspension_source` set to `AUTOMATIC`. Writing the certification outcome and driving the dispenser out of service are one mutation of the dispenser between them, so its `version` still advances by exactly one.

**Retirement.** A `NetworkOperator` retires a dispenser permanently; `RETIRED` is terminal for the availability dimension. Retirement is permitted from either `IN_SERVICE` or `OUT_OF_SERVICE`, and only while the dispenser's `maintenance_state` is `NONE` — an in-flight repair blocks it, and the attempt is rejected with `ERR_INVALID_STATE`. (The one place that precondition is waived is the station-teardown path of §3.3, which retires dispensers regardless of their repair posture.) Retirement stamps `retired_at` from the logical clock, decrements the station's out-of-service count when the dispenser was `OUT_OF_SERVICE`, recomputes the station's non-retired port count, `installed_power_kw` and `payment_interop_score`, and increments the dispenser's `version`. It does not reach the station's lifecycle dimension: retiring the last `OUT_OF_SERVICE` dispenser drives that count to zero without lifting an `AUTOMATIC` suspension, because only a dispenser *returning to service* runs the recovery cascade.

**The repair posture dimension.** A dispenser's `maintenance_state` evolves independently of its `service_state` and takes the values `NONE`, `DISPATCH_PENDING`, `UNDER_REPAIR`, and `AWAITING_PARTS`. It is the dispenser's *aggregate* repair posture, not a mirror of any single dispatch. When a first dispatch is created for a dispenser sitting at `NONE`, the dimension moves `NONE → DISPATCH_PENDING` and the dispenser's `version` is incremented — but this requires the dispenser not to be `RETIRED`. When a *further* dispatch is created for a dispenser already at `DISPATCH_PENDING`, `UNDER_REPAIR`, or `AWAITING_PARTS`, the dimension is left exactly where it is and the dispenser's `version` is **not** incremented. Multiple live dispatches on one dispenser are therefore legitimate; what keeps them apart is the window-overlap rule of §3.5, not this dimension.

The remaining moves on this dimension are all driven by dispatch progress: arrival advances `DISPATCH_PENDING → UNDER_REPAIR`, a parts hold advances `UNDER_REPAIR → AWAITING_PARTS`, resuming on site returns `AWAITING_PARTS → UNDER_REPAIR` (a dispatch may hold for parts any number of times), and completion returns `UNDER_REPAIR → NONE` — except that if another dispatch on the same dispenser is still live, in `CREATED`, `EN_ROUTE`, `ON_SITE`, or `PARTS_HOLD`, the dimension is re-derived as `DISPATCH_PENDING` instead of `NONE`. A station teardown that cancels the dispatch on a dispenser drives the dimension back to `NONE` from whichever of `DISPATCH_PENDING`, `UNDER_REPAIR`, or `AWAITING_PARTS` it occupied. Every one of these moves increments the dispenser's `version`.

### 3.3. Commissioning a Station, Suspending It, and Tearing It Down

A station's lifecycle dimension, `status`, runs over `DRAFT`, `COMMISSIONING`, `OPERATIONAL`, `SUSPENDED`, and `DECOMMISSIONED`, with `DECOMMISSIONED` terminal. Most moves are driven by a `NetworkOperator` naming the desired `target_status`; every one of them increments the station's `version`.

Entering commissioning takes the station `DRAFT → COMMISSIONING` and requires at least one non-retired dispenser to exist on it; a station with no dispensers is rejected with `ERR_INVALID_STATE`. The reverse leg, `COMMISSIONING → DRAFT`, is reserved for a `ComplianceAuditor` and is the audit-failure revert: when an interoperability audit fails, the auditor sends the station back to `DRAFT` for rework. `DRAFT` is the only target a `ComplianceAuditor` may request on this dimension.

**The commissioning gate ladder.** Commissioning proper is a separate operator action that advances `COMMISSIONING → OPERATIONAL`; a station standing in any other lifecycle state, `DECOMMISSIONED` included, is rejected with `ERR_INVALID_STATE` rather than with `ERR_ALREADY_TERMINAL`, since this action is not one of the `target_status` moves. Before the gate is evaluated, the server recomputes `payment_interop_score` from the station's current dispenser population. Then six gates are evaluated **in this order**, each with its own rejection:

1. The host site's `agreement_status` must be `EXECUTED`; otherwise `ERR_HOST_AGREEMENT_NOT_EXECUTED`.
2. The host site's `power_upgrade_status` must be either `NOT_REQUIRED` or `ENERGIZED`; a site still at `REQUESTED` or `IN_PROGRESS` yields `ERR_POWER_UPGRADE_NOT_ENERGIZED`.
3. The host site's `parking_enforcement_mode` must be `SIGNAGE_ONLY` or `TOWING_ENFORCED`; a site at `NONE` yields `ERR_PARKING_ENFORCEMENT_REQUIRED`.
4. The station's non-retired dispenser count must be at least as large as its `declared_port_count`; a shortfall yields `ERR_PORT_COUNT_BELOW_DECLARED`.
5. The station's `installed_power_kw` must not exceed the host site's `committed_service_capacity_kw`; exceeding it yields `ERR_SITE_CAPACITY_EXCEEDED`.
6. Finally, `payment_interop_score` must be at least 90.00. The boundary itself passes: a station scoring exactly 90.00 commissions. Anything below yields `ERR_INTEROP_SCORE_BELOW_THRESHOLD`.

Ordering the interoperability threshold last is deliberate — a station missing its paperwork should hear about the paperwork, not about its terminals. When all six gates clear, the station stamps `commissioned_at` from the logical clock (this happens the first time it reaches `OPERATIONAL`; before that the field is null), sets `suspension_source` to `NONE`, and increments its `version`.

**Suspension and resumption.** An operator may suspend an operational station directly, taking it `OPERATIONAL → SUSPENDED` and setting `suspension_source` to `MANUAL`. The system may also suspend it: whenever a dispenser on an operational station enters `OUT_OF_SERVICE` and the station's out-of-service count is therefore at least one, the station moves `OPERATIONAL → SUSPENDED` with `suspension_source` set to `AUTOMATIC`, its out-of-service count recomputed, and its `version` incremented.

Resumption mirrors that split. An operator may take a suspended station `SUSPENDED → OPERATIONAL` provided its out-of-service count is zero — otherwise the request is rejected with `ERR_INVALID_STATE` — and the move clears `suspension_source` back to `NONE`. The system performs the same move on its own when the *last* out-of-service dispenser returns to service, but only when `suspension_source` is `AUTOMATIC` and the count has reached zero. That guard is what prevents the recovery cascade from silently reversing a deliberate operator suspension.

**Teardown.** Decommissioning is reachable from any of `DRAFT`, `COMMISSIONING`, `OPERATIONAL`, or `SUSPENDED`, and it runs a three-link teardown regardless of which of those the station was in:

- **Link 1 — dispensers.** Every dispenser on the station whose `service_state` is `IN_SERVICE` or `OUT_OF_SERVICE` moves to `RETIRED`, with `retired_at` stamped from the logical clock and `maintenance_state` forced to `NONE`. The usual "no in-flight repair" precondition on retirement is waived here.
- **Link 2 — outages.** Because those dispensers retired, every outage on them sitting in `DETECTED`, `CLASSIFIED`, `DISPATCHED`, or `EXCLUSION_REVIEW` moves to `EXCLUDED`. Its `excluded_cause_claim` is forced to `HOST_SITE_CLOSURE`, its `excluded_at` is stamped from the logical clock, its `cleared_at` is stamped from the logical clock if and only if it was still null, and `pre_exclusion_state` records the state it left — normalised into that field's permitted pair, so a state left of `DETECTED` or `EXCLUSION_REVIEW` is recorded as `CLASSIFIED` and a state left of `DISPATCHED` is recorded as `RESOLVED`.
- **Link 3 — dispatches and depot stock.** Because those outages became excluded, every dispatch on them sitting in `CREATED`, `EN_ROUTE`, `ON_SITE`, or `PARTS_HOLD` moves to `CANCELLED`, and each of that dispatch's part reservations sitting in `RESERVED` or `BACKORDERED` moves to `RELEASED`, restoring the affected spare part's reserved and backordered quantities and therefore its unencumbered quantity.

The teardown then recomputes the station's non-retired dispenser count, out-of-service count, `installed_power_kw`, `payment_interop_score` and the full downtime ledger, sets `suspension_source` to `NONE`, decrements the host site's station count, and increments the station's `version`. Every entity touched at every link has its own `version` incremented.

### 3.4. Remote Monitoring, Fault Classification and Uptime Exclusions

Remote monitoring feeds faults into the system as **outage events**. A `NetworkOperator` ingests one by naming the `port_id` it was observed on, the vendor's non-empty `fault_code`, a `fault_class` drawn from `CRITICAL`, `MAJOR`, `MINOR`, or `INFORMATIONAL`, and the `detected_at` instant the monitor first saw it. An optional `excluded_cause_claim` may be asserted at ingestion; it defaults to `NONE` and is drawn from `NONE`, `UTILITY_OUTAGE`, `NATURAL_DISASTER`, `VANDALISM`, `HOST_SITE_CLOSURE`, and `EVSE_MANUFACTURER_RECALL`. A claim of `NONE` is not eligible for exclusion.

`detected_at` is bounded on both sides: it may not be later than the logical clock's current reading, or the request fails with `ERR_DETECTED_AT_IN_FUTURE`, and it may not be earlier than the dispenser's own `created_at`, or the request fails with `ERR_DETECTED_AT_BEFORE_PORT`. A new outage opens in `DETECTED` with `cleared_at`, `pre_exclusion_state`, `excluded_at` and `dispatch_created_by_user_id` all null and `is_system_generated` false. Ingestion is not gated on the dispenser's availability: a fault may be recorded against a `RETIRED` dispenser, and that row simply has nowhere to go, since classification refuses a retired dispenser.

Severity has an immediate consequence. When the ingested `fault_class` is `CRITICAL` or `MAJOR` and the dispenser is currently `IN_SERVICE`, the dispenser is driven `IN_SERVICE → OUT_OF_SERVICE`, the station's out-of-service count rises, and the station may in turn be automatically suspended. `MINOR` and `INFORMATIONAL` faults deliberately leave the dispenser in service — the network does not pull a working dispenser off the map for a cosmetic fault.

**Classification.** After triage a `NetworkOperator` classifies the outage, advancing it `DETECTED → CLASSIFIED` while overwriting `fault_class` with the payload value and, when supplied, `excluded_cause_claim` as well. Classification requires the dispenser not to be `RETIRED`; an outage on a retired dispenser is rejected with `ERR_PORT_RETIRED`. If the newly written `fault_class` is `CRITICAL` or `MAJOR` and the dispenser is still `IN_SERVICE`, classification drives the dispenser out of service exactly as ingestion would, which may suspend the station. The outage's `version` increments.

**Exclusion adjudication.** Not every minute of downtime is the operator's fault, and the programme recognises specific excluded causes. A `NetworkOperator` opens an exclusion by submitting an `action` of `REQUEST`, optionally carrying a revised `excluded_cause_claim`. A request is permitted only from `CLASSIFIED` or `RESOLVED`, only while the dispenser is not `RETIRED`, and only while `excluded_cause_claim` is something other than `NONE` — a claim of `NONE` is rejected with `ERR_EXCLUSION_CAUSE_NOT_ELIGIBLE`. The outage moves to `EXCLUSION_REVIEW` and records which state it came from in `pre_exclusion_state`: `CLASSIFIED` when requested from `CLASSIFIED`, `RESOLVED` when requested from `RESOLVED`. Its `version` increments.

A `ComplianceAuditor` then submits one of three actions; on all three an `excluded_cause_claim` carried in the body is validated for shape and then ignored, so the effective cause is always the one already stored on the outage, and the `REQUEST` leg above is the only place an exclusion action rewrites it. `APPROVE` requires the outage to be in `EXCLUSION_REVIEW` with an effective cause other than `NONE` and moves it `EXCLUSION_REVIEW → EXCLUDED`; it stamps `excluded_at` from the logical clock, leaves `pre_exclusion_state` standing — which is what lets a later `REVOKE` find it — shifts the station's `excluded_downtime_minutes_lifetime` and `billable_downtime_minutes_lifetime` (the gross figure is unchanged, because the minutes did not disappear — they merely stopped being the operator's), sends every `PROVISIONAL` uptime report on that station back to `DRAFT` with `methodology`, `uptime_pct`, `excluded_minutes`, `billable_downtime_minutes`, `total_port_minutes` and `eligible_port_count` all reset to null, and — when the state left was `CLASSIFIED` — returns the dispenser `OUT_OF_SERVICE → IN_SERVICE` provided no other unresolved outage remains on it. The outage's `version` increments.

`REJECT` requires the outage to be in `EXCLUSION_REVIEW` with `pre_exclusion_state` set — a null `pre_exclusion_state` is answered with `ERR_EXCLUSION_CAUSE_NOT_ELIGIBLE`, and the same code answers a `REVOKE` on an `EXCLUDED` outage that records no prior state — and restores exactly that state: back to `CLASSIFIED` when `pre_exclusion_state` is `CLASSIFIED`, back to `RESOLVED` when it is `RESOLVED`. Either way `pre_exclusion_state` is cleared to null and the `version` increments.

`REVOKE` is the compensating action for an approval that should not have stood. It requires the outage to be in `EXCLUDED` with `pre_exclusion_state` set, clears both `excluded_at` and `pre_exclusion_state` to null, reverses the excluded/billable ledger shift (again leaving the gross figure untouched), and sends every `PROVISIONAL` report on the station back to `DRAFT` with the same computed fields reset to null. Its destination is symmetric with `REJECT`: `EXCLUDED → RESOLVED` when `pre_exclusion_state` is `RESOLVED`, and `EXCLUDED → CLASSIFIED` when it is `CLASSIFIED`. The `CLASSIFIED` branch additionally drives the dispenser `IN_SERVICE → OUT_OF_SERVICE` when the outage's `fault_class` is `CRITICAL` or `MAJOR`, because the fault is live again. The `version` increments on both branches.

**Post-repair review.** Once a repair has closed an outage it sits in `RESOLVED` awaiting review, and the review has two outcomes. An `outcome` of `VERIFY`, available to a `ComplianceAuditor`, closes the outage `RESOLVED → VERIFIED` — the terminal state of this dimension — and is subject to SoD-1: the reviewer's `X-User-ID` must differ from the outage's `dispatch_created_by_user_id`. An `outcome` of `REOPEN`, available to a `NetworkOperator`, sends it `RESOLVED → CLASSIFIED`, clears `cleared_at` back to null, reverses the station's gross and billable downtime figures, and — when `fault_class` is `CRITICAL` or `MAJOR` — drives the dispenser `IN_SERVICE → OUT_OF_SERVICE` again, which may re-suspend the station. Reopening requires the dispenser not to be `RETIRED`, failing with `ERR_PORT_RETIRED` otherwise. Both outcomes increment the outage's `version`. Reopening is what closes the loop `CLASSIFIED → DISPATCHED → RESOLVED → CLASSIFIED`: a fault that was declared fixed but was not can be sent round the repair cycle again.

**The station downtime ledger.** The station's three lifetime downtime figures are recomputed whenever an outage on any of its dispensers gains or loses a `cleared_at`, or enters or leaves `EXCLUDED`. The ledger set is every outage on every dispenser of the station — including dispensers that have since been retired — restricted to outages that actually have a `cleared_at`; an outage still open contributes nothing to any of the three figures. Each member of that set contributes its closed duration, the elapsed time from `detected_at` to `cleared_at` in whole minutes with any partial minute discarded. `gross_downtime_minutes_lifetime` is the sum of those durations over the whole set; `excluded_downtime_minutes_lifetime` is the sum over just those members currently in `EXCLUDED`; and `billable_downtime_minutes_lifetime` is the gross figure less the excluded figure.

### 3.5. Dispatching Field Maintenance Inside the Response Window

A classified fault is worked by dispatching a technician. A `NetworkOperator` creates a **maintenance dispatch** naming the `outage_event_id` it is sent to clear, the `port_id` the technician is assigned to, the non-empty opaque `technician_user_id` of the assignee, that assignee's highest `technician_certification_class` — one of `L2`, `DCFC_BASIC`, or `DCFC_HV` — and the planned on-site window as `window_start_at` and `window_end_at`. The dispatch opens in `CREATED` with `arrived_at`, `response_met`, `promised_repair_at` and `total_hold_minutes` all null, and `created_by_user_id` set to the creating operator's `X-User-ID`.

Four checks guard creation, and they fire in the precedence order of §2.11 — behind two state preconditions that come first, both rejected with `ERR_INVALID_STATE`: the outage must be standing in `CLASSIFIED`, and the dispenser named by `port_id` must not be `RETIRED` (that second refusal is `ERR_INVALID_STATE`, not `ERR_PORT_RETIRED`). The `port_id` must be the same dispenser the outage was reported on; a mismatch is rejected with `ERR_OUTAGE_PORT_MISMATCH`. The technician's certification must cover the power class of the station holding the *outage's* dispenser, which is the same station whenever the two identifiers agree: certification ranks in the order `L2`, then `DCFC_BASIC`, then `DCFC_HV`, and the station's requirement ranks in the parallel order `L2_19`, then `DCFC_150`, then `DCFC_350`, so a `DCFC_350` station requires `DCFC_HV`, a `DCFC_150` station requires `DCFC_BASIC` or `DCFC_HV`, and an `L2_19` station accepts any of the three. A technician ranked below the station's requirement is rejected with `ERR_TECHNICIAN_NOT_CERTIFIED`. The window must be well-formed: `window_end_at` strictly after `window_start_at`, and `window_start_at` no earlier than the outage's `detected_at`, or the request fails with `ERR_DISPATCH_WINDOW_INVALID`. And the window must not collide, under the half-open convention of §2.10, with the window of any other dispatch on the same dispenser that is still live in `CREATED`, `EN_ROUTE`, `ON_SITE`, or `PARTS_HOLD`; a genuine intersection is rejected with `ERR_DISPATCH_WINDOW_OVERLAP`, while windows that merely touch at an endpoint are accepted.

Creation also propagates. The outage advances `CLASSIFIED → DISPATCHED`, recording the creating operator's `X-User-ID` as `dispatch_created_by_user_id` — the value SoD-1 will later compare against — and the dispenser's repair posture moves `NONE → DISPATCH_PENDING` under the aggregate rule of §3.2.

**The response deadline.** Every dispatch is stamped at creation with a contractual `response_deadline_at`, and it is computed once and never moved afterwards from the outage named by `outage_event_id`, that outage's dispenser's station, and that station's host site. Four inputs interact:

First, a base allowance is chosen from the outage's severity: four hours for `CRITICAL`, twelve hours for `MAJOR`, forty-eight hours for `MINOR`, and seven days for `INFORMATIONAL`. Second, that base is scaled by the station's power class — halved for `DCFC_350`, reduced to three quarters for `DCFC_150`, and left unchanged for `L2_19` — with the scaled product rounded down to a whole number of minutes. Third, if the station is `corridor_designated`, one hour is subtracted from the scaled figure; otherwise nothing is subtracted. Fourth, the result is clamped into the regulatory band: it is raised to two hours if it fell below two hours, and capped at three days if it rose above three days. The clamped allowance is added to the outage's `detected_at` to give a provisional deadline instant.

That provisional instant is then reconciled against the host site's access hours, because a technician cannot arrive at a locked site. If the host site's `access_hours_mode` is `TWENTY_FOUR_SEVEN`, the provisional instant is the deadline. If the mode is `RESTRICTED`, the server takes the provisional instant's minute of the UTC day (its hour multiplied by sixty, plus its minute) and compares it to the access window. When that minute is at or after `access_open_minute` and strictly before `access_close_minute`, the provisional instant stands. When it falls before `access_open_minute`, the deadline is pushed forward to `access_open_minute` on the same UTC date, with seconds and milliseconds zeroed. When it falls at or after `access_close_minute`, the deadline is pushed to `access_open_minute` on the next UTC date, again with seconds and milliseconds zeroed.

**Working the dispatch.** Progress is posted by the assigned `FieldTechnician` only — anyone else is rejected with `ERR_NOT_ASSIGNED_TECHNICIAN` — as an `event` drawn from `EN_ROUTE`, `ARRIVE`, and `RESUME_ONSITE`. Each event increments the dispatch's `version`.

`EN_ROUTE` advances the dispatch `CREATED → EN_ROUTE` and additionally requires the station to be serviceable, meaning its `status` is `OPERATIONAL` or `SUSPENDED`; a dispatch against a station in any other lifecycle state is rejected with `ERR_STATION_NOT_SERVICEABLE`. `ARRIVE` advances `EN_ROUTE → ON_SITE`, stamps `arrived_at` from the logical clock, and settles `response_met` once and for all: it is true when `arrived_at` is at or before `response_deadline_at` and false otherwise, and it stays null until arrival is posted. Arrival also drives the dispenser's repair posture `DISPATCH_PENDING → UNDER_REPAIR`. `RESUME_ONSITE` returns a held dispatch `PARTS_HOLD → ON_SITE` and drives the repair posture `AWAITING_PARTS → UNDER_REPAIR`, leaving `total_hold_minutes` and `promised_repair_at` at the values the hold wrote until a later hold recomputes them; completion does not clear them either.

**Completion — the recovery cascade.** The assigned technician closes the dispatch out from `ON_SITE`, but only when no part reservation on it is still `BACKORDERED`; an outstanding backorder is rejected with `ERR_INVALID_STATE`. Completion runs four links:

- The dispatch moves `ON_SITE → COMPLETED`, and every reservation on it still in `RESERVED` moves to `CONSUMED`, drawing the corresponding spare part's on-hand and reserved quantities down by the reservation's quantity and raising its lifetime consumed quantity by the same amount.
- The outage moves `DISPATCHED → RESOLVED` with `cleared_at` stamped from the logical clock, and the station's gross and billable lifetime downtime figures are recomputed.
- Because no unresolved outage remains on the dispenser, it returns `OUT_OF_SERVICE → IN_SERVICE` and its repair posture returns `UNDER_REPAIR → NONE` (or is re-derived as `DISPATCH_PENDING` if another dispatch on that dispenser is still live).
- Because the station's out-of-service count reached zero, a station suspended with `suspension_source` of `AUTOMATIC` returns `SUSPENDED → OPERATIONAL` with `suspension_source` cleared to `NONE`.

A dispenser returns to service only when no outage on it remains in `DETECTED`, `CLASSIFIED`, `DISPATCHED`, or `EXCLUSION_REVIEW`, and only when its `terminal_certification_status` is not `REVOKED` — a revoked terminal keeps the dispenser out of service no matter how many faults are cleared.

The other exit from a live dispatch is cancellation, which is never a client action: a dispatch in `CREATED`, `EN_ROUTE`, `ON_SITE`, or `PARTS_HOLD` moves to `CANCELLED` only through the station teardown of §3.3, releasing its `RESERVED` and `BACKORDERED` reservations as it goes. `COMPLETED` and `CANCELLED` are both terminal.

### 3.6. Depot Inventory, Backorders and the Parts-Hold Promise

The depot is modelled as **spare parts** and the **reservations** that encumber them. A `NetworkOperator` creates a part record with a globally unique manufacturer `part_number` (a collision yields `ERR_PART_NUMBER_DUPLICATE`), a `part_class` drawn from `DISPENSER`, `POWER_MODULE`, `CABLE_ASSEMBLY`, and `PAYMENT_TERMINAL`, and the vendor's `lead_time_days`, a whole number of days that may be zero but never negative. Stock starts empty: `on_hand_qty` opens at zero and is raised only by restocking.

Four derived quantities describe the part's encumbrance, all of them zero on a fresh record. `reserved_qty` is the total quantity across the part's reservations currently in `RESERVED`; `backordered_qty` is the same total across reservations in `BACKORDERED`; `consumed_qty_lifetime` accumulates the quantity across reservations that reached `CONSUMED`; and `unencumbered_qty` — the figure the reserve/release pair conserves — is `on_hand_qty` less `reserved_qty`.

**Restocking.** Receiving stock raises `on_hand_qty`, and therefore the unencumbered figure, by the `qty` received, which must be an integer of at least 1 — anything else is rejected with `ERR_INVALID_REQUEST`. It then works through the part's backordered reservations in ascending `created_at` order, promoting each one to `RESERVED` for as long as the available stock covers it — and the pool it draws on is the part's whole unencumbered figure *after* the receipt, `on_hand_qty` less `reserved_qty`, not merely the units just received: promotion moves that reservation's quantity from `backordered_qty` to `reserved_qty` and clears its `expected_available_at` to null. Promotion stops at the first queued reservation the remaining pool does not cover, and every reservation behind that one stays backordered even where a smaller line further down would still have fitted. Restocking increments the part's `version`, and each promoted reservation's `version` as well.

**Earmarking stock.** A `NetworkOperator` creates a reservation naming the `dispatch_id` the parts are for, the `spare_part_id` being earmarked, the `qty` of units, and the `expected_spare_part_version` guard of §2.7. The dispatch's own state is never a precondition here — stock may be earmarked against a dispatch standing anywhere in its lifecycle, `COMPLETED` and `CANCELLED` included. The quantity must be at least 1; anything lower is rejected with `ERR_RESERVATION_QTY_INVALID`. Whether the reservation is satisfiable is decided at creation time by comparing the requested quantity against the part's unencumbered figure — its on-hand quantity less its already-reserved quantity. If the quantity is covered, the reservation is created in `RESERVED`, the part's `reserved_qty` rises by that quantity, and `expected_available_at` stays null. If the quantity exceeds the unencumbered figure, the reservation is created directly in `BACKORDERED` — the response already reports that state — the part's `backordered_qty` rises by that quantity instead, and `expected_available_at` is set to the logical clock's current reading advanced by the part's `lead_time_days` days. Either way the part's `version` increments.

**Disposing of a reservation.** Two dispositions exist, selected by an `action`. `CONSUME` is the technician's action and is permitted only by the dispatch's assigned technician (otherwise `ERR_NOT_ASSIGNED_TECHNICIAN`), only from `RESERVED`, and only while the owning dispatch is in `ON_SITE` or `PARTS_HOLD`. It moves the reservation `RESERVED → CONSUMED`, lowers the part's `on_hand_qty` and `reserved_qty` each by the reservation's quantity, and raises `consumed_qty_lifetime` by the same quantity — leaving the unencumbered figure exactly where it was, because the units left the shelf and the earmark at the same time. `RELEASE` is the operator's compensating action and is permitted from either `RESERVED` or `BACKORDERED`. From `RESERVED` it moves the reservation `RESERVED → RELEASED` and lowers `reserved_qty` by the quantity, restoring the unencumbered figure to its pre-reservation value; from `BACKORDERED` it moves the reservation `BACKORDERED → RELEASED`, lowers `backordered_qty` by the quantity, and clears `expected_available_at` back to null. A release aimed at a reservation that no longer encumbers stock is rejected with `ERR_RESERVATION_QTY_INVALID`. Both dispositions increment the reservation's `version` and the part's `version`. `CONSUMED` and `RELEASED` are terminal. The same two moves also occur without a client action — consumption on dispatch completion, release on dispatch cancellation during a station teardown.

**The parts-hold promise.** When a technician on site cannot finish for want of parts, they place a **parts hold**, taking the dispatch `ON_SITE → PARTS_HOLD` and the dispenser's repair posture `UNDER_REPAIR → AWAITING_PARTS`. A hold requires at least one reservation on the dispatch to be in `RESERVED` or `BACKORDERED`; with nothing outstanding the request is rejected with `ERR_INVALID_STATE`. The hold recomputes `total_hold_minutes` and `promised_repair_at`, and it may be placed any number of times over a dispatch's life — each hold recomputes the promise from scratch, so releasing a reservation between two holds genuinely changes the answer.

The promise considers only the reservations on this dispatch that are in `RESERVED` or `BACKORDERED`; released and consumed reservations, and every other dispatch's reservations, are ignored. It is built in a pinned order:

1. Each considered reservation contributes a wait: a backordered reservation contributes its part's `lead_time_days` converted to minutes at one thousand four hundred and forty minutes per day, while a reservation that is merely reserved contributes zero.
2. The raw parts wait is the largest of those contributions — the slowest blocking line sets the pace. With nothing considered, the raw wait is zero.
3. The labour allowance is keyed on the most labour-intensive part class among the considered reservations: eight hours for `DISPENSER`, five hours for `POWER_MODULE`, three hours for `CABLE_ASSEMBLY`, and two hours for `PAYMENT_TERMINAL`, taking the largest of those where several classes are held. With nothing considered, the labour allowance is two hours.
4. The pre-expedite total is the raw parts wait plus the labour allowance.
5. Expedite eligibility is decided **once**, on that pre-expedite total, and strictly: the dispatch qualifies for expediting only when the pre-expedite total is *greater than* two days. It is deliberately not re-tested after the discount is applied, even though the discounted total frequently falls back below that trigger — re-testing would flip eligibility off and leave the value undefined.
6. When the dispatch qualifies, the raw parts wait — and only the wait component, never the labour — is halved, with the halved figure rounded **up** to a whole minute. When it does not qualify, the raw wait stands unchanged.
7. `total_hold_minutes` is the final parts wait plus the labour allowance, and `promised_repair_at` is the logical clock's current reading advanced by that many minutes.

### 3.7. Uptime Reporting: The Provisional View and the Federal View

An **uptime report** is a station-scoped reporting period plus the figures computed over it. A `NetworkOperator` declares one by naming the `station_id`, the inclusive `period_start`, and the inclusive `period_end`. The period must be well-formed and elapsed: `period_end` strictly after `period_start` and spanning at least seven days, or the request fails with `ERR_REPORTING_PERIOD_INVALID`; and `period_end` no later than the logical clock's current reading, or it fails with `ERR_REPORTING_PERIOD_NOT_ELAPSED`. It must also not collide with any existing report period on the same station, in any state, under the closed-interval convention of §2.10 — a genuine intersection *or* a merely adjacent period is rejected with `ERR_REPORTING_PERIOD_OVERLAP`.

A fresh report opens in `DRAFT` with `methodology`, `eligible_port_count`, `total_port_minutes`, `excluded_minutes`, `billable_downtime_minutes` and `uptime_pct` all null, `finalized_by_user_id` null, `claim_count` zero, and `returned_count` zero.

**How the figures are built.** Both methodologies share the same population and the same downtime attribution; they diverge only in the denominator.

The period length is the elapsed time from `period_start` to `period_end` expressed in whole minutes, with any partial minute discarded. A dispenser is *eligible* for the report when it belongs to the report's station, its own `created_at` is at or before `period_start`, and its `service_state` is `IN_SERVICE` or `OUT_OF_SERVICE`. `eligible_port_count` is the number of such dispensers, and `total_port_minutes` — the report's total exposure — is that count multiplied by the period length. A dispenser installed after `period_start`, or already retired, contributes no port-minutes at all, and its outages are dropped from the attribution as well.

An outage is *attributed* to the period when it sits on an eligible dispenser, its `detected_at` is strictly before `period_end`, and either its `cleared_at` is null or its `cleared_at` is strictly after `period_start`. Each attributed outage contributes the portion of its downtime that falls inside the period: the overlap starts at the later of `detected_at` and `period_start`, ends at the earlier of `period_end` and either `cleared_at` or — for an outage still open — `period_end` itself, and the elapsed time between those two instants is taken in whole minutes with any partial minute discarded and with a negative result treated as zero. An uncleared outage is therefore charged right through to the end of the period.

Those per-outage overlaps are then split into two buckets. `excluded_minutes` is the sum of overlaps over attributed outages currently in `EXCLUDED`. `billable_downtime_minutes` is the sum of overlaps over attributed outages in every other state — `DETECTED`, `CLASSIFIED`, `DISPATCHED`, `RESOLVED`, `VERIFIED`, and `EXCLUSION_REVIEW`. Every attributed outage lands in exactly one bucket; the sums are order-insensitive.

**The provisional computation.** A `NetworkOperator` computes the provisional figure, advancing the report `DRAFT → PROVISIONAL`. The station must be serviceable — its `status` must be `OPERATIONAL` or `SUSPENDED`, and a station outside that pair is rejected with `ERR_INVALID_STATE`, not with `ERR_STATION_NOT_SERVICEABLE` — and the total exposure must be greater than zero, or the request fails with `ERR_NO_REPORTABLE_PORT_MINUTES`. Under the provisional methodology, excluded minutes are credited in the **numerator only**: the figure is one hundred multiplied by the total exposure less the excluded minutes less the billable downtime minutes, all divided by the total exposure, rounded half up to two decimal places. The denominator stays at the station's full port-minute exposure, which is why an operator with excluded outages reports a *lower* number here than the federal methodology will yield. The computation writes `eligible_port_count`, `total_port_minutes`, `excluded_minutes`, `billable_downtime_minutes` and `uptime_pct`, sets `methodology` to `PROVISIONAL`, and increments the report's `version`.

**Finalisation.** A `ComplianceAuditor` finalises the report, advancing it `PROVISIONAL → FINAL`. Two guards apply. No outage attributed to the period may still be sitting in `EXCLUSION_REVIEW`, or the request fails with `ERR_EXCLUSION_REVIEW_PENDING` — a pending exclusion adjudication would make the number provisional in fact even if the state said otherwise. And the total exposure less the excluded minutes must be greater than zero, or the request fails with `ERR_NO_REPORTABLE_PORT_MINUTES`. Under the final federal methodology, excluded minutes leave **both** numerator and denominator: the figure is one hundred multiplied by the total exposure less the excluded minutes less the billable downtime minutes, divided by the total exposure less the excluded minutes, rounded half up to two decimal places. Whenever there is at least one excluded minute and at least one billable downtime minute, the final figure over identical rows is strictly greater than the provisional figure. Finalisation sets `methodology` to `FINAL`, stores the acting auditor's `X-User-ID` as `finalized_by_user_id` for SoD-2, and increments the report's `version`.

**Invalidation.** Because the exclusion ledger can move under a report, an outage on the station being approved for exclusion — or having an approved exclusion revoked — sends every `PROVISIONAL` report on that station back `PROVISIONAL → DRAFT`, resetting `methodology`, `eligible_port_count`, `total_port_minutes`, `excluded_minutes`, `billable_downtime_minutes` and `uptime_pct` to null and incrementing the report's `version`. The operator must recompute before the report can be finalised again.

**Submission and programme review.** A `NetworkOperator` submits a finalised report to the programme, advancing it `FINAL → SUBMITTED` and incrementing its `version`. A `ProgramAdministrator` then decides it with an `outcome`. `ACCEPT` advances `SUBMITTED → ACCEPTED`, the terminal state, and makes the report claimable. `RETURN` sends it `SUBMITTED → PROVISIONAL`, raises `returned_count` by one, and clears `finalized_by_user_id` back to null — which both records the round trip and releases the SoD-2 bar until a new auditor finalises. Either outcome increments the report's `version`. The return leg closes the cycle `PROVISIONAL → FINAL → SUBMITTED → PROVISIONAL`, and a report may travel it any number of times.

### 3.8. Reimbursement Claims, Withhold Tiers and Remediation

Programme money is drawn against an accepted report — though that acceptance is enforced only when adjudication opens, so filing itself tests nothing about the report's `state` and a claim may be filed against a report still sitting in `DRAFT`. A `NetworkOperator` files a **reimbursement claim** naming the `uptime_report_id`, the `line_items` being claimed, and the `expected_uptime_report_version` guard of §2.7. Each entry in `line_items` is an object with a `port_id`, a `category` drawn from `OANDM`, `NETWORK_FEES`, and `PARTS`, and an `amount_cents` that may be zero but never negative. The array must hold at least one entry, or the filing is rejected with `ERR_CLAIM_LINE_ITEMS_EMPTY`, and every `port_id` in it must belong to the report's station, or the filing is rejected with `ERR_CLAIM_LINE_PORT_MISMATCH`. **The order in which the entries are supplied is significant and is preserved** — it is the rounding order the withhold computation will use.

Filing writes `requested_amount_cents` as the exact integer sum of the line-item amounts, opens the claim in `PENDING` with `remediation_credit_pp` at `0`, `effective_uptime_pct`, `withhold_rate`, `withheld_amount_cents`, `approved_amount_cents` and `decided_by_user_id` all null, drives any existing `PENDING` claim on the same report to `SUPERSEDED` (incrementing that claim's `version`), raises the report's `claim_count`, and increments the report's `version`.

**Opening adjudication.** A `ProgramAdministrator` opens the claim for adjudication, moving it `PENDING → REVIEW` or, after a withhold, `WITHHELD → REVIEW`. The report must be in `ACCEPTED`, or the request is rejected with `ERR_UPTIME_REPORT_NOT_ACCEPTED`. Entering review takes the **snapshot** on which the money rests, and the snapshot is what makes the whole computation well-defined:

1. The credit in play is the claim's `remediation_credit_pp`, in percentage points — zero unless a remediation has been accepted.
2. `effective_uptime_pct` is the report's `uptime_pct` plus that credit, rounded half up to two decimal places, and then capped at 100.00 — the credit can never carry a station past perfect uptime.
3. `withhold_rate` is selected from `effective_uptime_pct` by walking the tiers from the top with an inclusive comparison at each step: an effective figure of at least 97.00 withholds nothing (a rate of `0.00`); otherwise at least 95.00 withholds a tenth (`0.10`); otherwise at least 90.00 withholds a quarter (`0.25`); and anything below 90.00 withholds the whole claim (`1.00`).

Only the claim's own `line_items` and the `uptime_pct` of the single report named by `uptime_report_id` feed this; other claims on the same report, superseded ones included, contribute nothing. Opening review increments the claim's `version`.

**Deciding.** The same role then submits a `decision`, and the decision must agree with the snapshotted tier. Every decision is subject to SoD-2: the deciding `X-User-ID` must differ from the report's `finalized_by_user_id`, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. Every decision also records `decided_by_user_id` as the acting `X-User-ID` and increments the claim's `version`.

- `APPROVE` requires the snapshotted `withhold_rate` to be exactly `0.00`, that is an `effective_uptime_pct` of at least 97.00. Anything else is rejected with `ERR_UPTIME_BELOW_APPROVAL_THRESHOLD`. It moves the claim `REVIEW → APPROVED`, sets `withheld_amount_cents` to zero and `approved_amount_cents` to `requested_amount_cents`.
- `WITHHOLD` requires the snapshotted `withhold_rate` to be strictly greater than `0.00` and strictly less than `1.00`; a rate of `0.00` or `1.00` is rejected with `ERR_WITHHOLD_RATE_MISMATCH`. It moves the claim `REVIEW → WITHHELD` and computes the money as described below.
- `DENY` requires the snapshotted `withhold_rate` to be exactly `1.00`; anything else is rejected with `ERR_WITHHOLD_RATE_MISMATCH`. It moves the claim `REVIEW → DENIED`, sets `withheld_amount_cents` to `requested_amount_cents` and `approved_amount_cents` to zero.

**The pinned rounding order.** On a withhold, `withheld_amount_cents` is computed by walking the `line_items` in the order they were supplied at filing, multiplying each entry's `amount_cents` by the snapshotted `withhold_rate`, rounding **each product** half up to a whole cent, and summing those rounded per-item withholds. Rounding per item before summation is the rule; summing first and rounding once is explicitly *not* the rule, and the two give different cent totals — three line items of 1005 cents each at a tenth withhold give 303 cents per item, where sum-then-round would give 302. `approved_amount_cents` is then `requested_amount_cents` less `withheld_amount_cents`.

**Remediation.** A withheld claim is not the end of the story. A `NetworkOperator` may file a remediation against it, supplying a non-optional `remediation_credit_pp` in percentage points of uptime credit — any number, rounded half up to two decimals, with no bound imposed at either end — which moves the claim `WITHHELD → REVIEW`, writes that credit onto the claim, and re-runs the snapshot — recomputing `effective_uptime_pct` (still capped at 100.00) and re-selecting `withhold_rate` from the tiers. That closes the cycle `REVIEW → WITHHELD → REVIEW`, and the fact that the credit is *pinned* into the snapshot at each review entry is exactly what keeps the withhold arithmetic single-valued. `APPROVED`, `DENIED`, and `SUPERSEDED` are all terminal.

### 3.9. Driver Complaints and Session Refunds

The driver-facing side of reliability is a complaint desk. A `CustomerSupportAgent` takes a **complaint** naming the `station_id` complained about, the `port_id` the driver used, a `complaint_type` drawn from `PAYMENT_DECLINED`, `PRICE_MISMATCH`, `SESSION_FAILED`, `CHARGER_OFFLINE`, and `BLOCKED_STALL`, and the disputed session's full billing detail: `session_started_at`, `session_ended_at`, the `session_energy_kwh` actually delivered (to three decimals, never negative), the posted `session_price_per_kwh_cents` that applied (whole cents, never negative), and the `session_charged_cents` actually taken from the driver's payment instrument. An optional `session_idle_fee_cents` records the idle or occupancy component already included inside the charged total; it defaults to zero and may not be negative.

Three checks guard intake. The dispenser must belong to the station named — otherwise `ERR_COMPLAINT_PORT_MISMATCH`. The session must be well-formed, with `session_ended_at` strictly after `session_started_at` — otherwise `ERR_SESSION_WINDOW_INVALID`. And the charged total may not be smaller than the idle-fee component it is supposed to contain — otherwise `ERR_SESSION_CHARGE_INVALID`. A fresh complaint opens with `state` at `INTAKE` and `refund_state` at `NONE`, with `linked_outage_event_id`, `refund_basis`, `refund_amount_cents`, `retained_amount_cents`, `refund_requested_by_user_id` and `refund_settled_at` all null.

A complaint carries **two independent dimensions**. The intake dimension, `state`, runs over `INTAKE`, `TRIAGED`, `CLOSED`, and `DISMISSED`. The money dimension, `refund_state`, runs over `NONE`, `REQUESTED`, `APPROVED`, `DENIED`, `SETTLED`, and `REVERSED`. They advance separately, and the guards between them are stated explicitly below.

**Triage.** The support agent triages an `INTAKE` complaint with a `disposition`. `LINK_OUTAGE` attributes the complaint to a fault and advances `INTAKE → TRIAGED`: it requires a `linked_outage_event_id` naming an outage whose dispenser is the same one the complaint names, or the request is rejected with `ERR_COMPLAINT_OUTAGE_MISMATCH` — an omitted identifier draws that same error rather than `ERR_INVALID_REQUEST` — and it writes that identifier onto the complaint. `NO_FAULT` dismisses the complaint, advancing `INTAKE → DISMISSED`, and is permitted only while the money dimension is still at `NONE`. Either disposition increments the complaint's `version`.

**Closing.** A triaged complaint is closed by the support agent, advancing `TRIAGED → CLOSED`. Closure is blocked while the money dimension is still in flight: it is permitted only when `refund_state` is `NONE`, `DENIED`, `SETTLED`, or `REVERSED`, and an attempt while `refund_state` is `REQUESTED` or `APPROVED` is rejected with `ERR_REFUND_IN_FLIGHT`. `CLOSED` and `DISMISSED` are both terminal for the intake dimension.

**Requesting a refund.** The support agent files a refund on the money dimension, advancing `refund_state` from `NONE` to `REQUESTED`. Two guards apply: the money dimension must be at `NONE`, and — the cross-dimension guard — the intake dimension must already be at `TRIAGED`. The request carries a `refund_basis`, which is either `ENERGY_PRORATED` or `FULL_SESSION_GOODWILL`; the field is null before any request is filed. Filing writes `refund_basis`, `refund_amount_cents` and `retained_amount_cents`, records the acting `X-User-ID` as `refund_requested_by_user_id`, and increments the complaint's `version`.

The amount is computed from the complaint's own session fields plus, at most, the single outage named by `linked_outage_event_id`; no other complaint on the same dispenser or station participates. The server first values the energy the driver actually received: the delivered `session_energy_kwh` multiplied by the posted `session_price_per_kwh_cents`, with that product rounded half up to a whole cent.

Under **`ENERGY_PRORATED`** — the default remedy when a session over-billed relative to what it delivered — `refund_amount_cents` is the charged total less that energy value less the idle-fee component, floored at zero so it can never go negative. The driver keeps paying for energy actually received and never gets the idle fee back.

Under **`FULL_SESSION_GOODWILL`**, an eligibility gate runs **before** any amount is computed. The complaint must have a `linked_outage_event_id`; that outage's `fault_class` must be `CRITICAL`; and that outage's downtime window must overlap the disputed session under the half-open convention of §2.10, the outage running from its `detected_at` inclusive up to its `cleared_at` exclusive (or forward without bound while `cleared_at` is null) and the session running from `session_started_at` inclusive to `session_ended_at` exclusive, with a zero-length touch not counting as an overlap. Failing any of the three yields `ERR_REFUND_BASIS_NOT_ELIGIBLE`. When the gate clears, `refund_amount_cents` is the entire `session_charged_cents`, idle fee included. Over identical complaint rows the two bases produce different refunds whenever the energy value and the idle fee together come to anything at all.

`retained_amount_cents` is always `session_charged_cents` less `refund_amount_cents`. That pairing is the invariant of this whole chain: **the refund and the retained amount always sum to exactly what the driver was charged**, at every point in the money dimension.

**Deciding the refund.** A `ComplianceAuditor` decides a requested refund with a `decision`. `APPROVE` advances `refund_state` from `REQUESTED` to `APPROVED`, but only when `refund_amount_cents` does not exceed `session_charged_cents`; a refund larger than the charge is rejected with `ERR_REFUND_EXCEEDS_SESSION_CHARGE`. `DENY` advances `REQUESTED → DENIED` and rewrites the money split to the no-refund position: `refund_amount_cents` becomes zero and `retained_amount_cents` becomes the full `session_charged_cents`. Both decisions increment the complaint's `version`.

**Moving the money.** An approved refund is paid or clawed back through a ledger `action`. `SETTLE` is the support agent's action: it advances `refund_state` from `APPROVED` to `SETTLED`, stamps `refund_settled_at` from the logical clock, and raises the station's `refund_liability_cents` by the refund amount. `REVERSE` is the auditor's compensating action: it advances `SETTLED → REVERSED`, clears `refund_settled_at` back to null, lowers the station's `refund_liability_cents` by the refund amount — restoring it to its exact pre-settlement value — and rewrites the money split to the no-refund position, setting `refund_amount_cents` to zero and `retained_amount_cents` to the full `session_charged_cents`. Both actions increment the complaint's `version`. `DENIED` and `REVERSED` are terminal for the money dimension.

## 4. Endpoint Definitions

Operations that bring a new stand-alone resource into existence — a host site, a station, a charging port, an outage event, a maintenance dispatch, a spare part, a part reservation, an uptime report, a reimbursement claim, or a customer complaint — return `201 Created`. Every other successful operation, including every state transition, every amendment, and every read, returns `200 OK`. Roles listed as "Any" mean all six declared roles.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server's logical clock to the supplied instant | Any |
| POST | `/host-sites` | Register a host site | NetworkOperator |
| GET | `/host-sites` | List host sites | Any |
| GET | `/host-sites/{host_site_id}` | Fetch one host site | Any |
| GET | `/host-sites/{id}/stations` | List stations installed at this host site | Any |
| PATCH | `/host-sites/{host_site_id}` | Amend the host site agreement | NetworkOperator, HostSiteManager |
| POST | `/stations` | Create a station in `DRAFT` at a host site | NetworkOperator |
| GET | `/stations/{station_id}` | Fetch one station with its counters, score and downtime ledger | Any |
| GET | `/stations/{id}/charging-ports` | List charging ports belonging to this station | Any |
| GET | `/stations/{id}/uptime-reports` | List reporting periods declared for this station | Any |
| POST | `/stations/{station_id}/status-transitions` | Operator-driven station lifecycle move | NetworkOperator, ComplianceAuditor |
| POST | `/stations/{station_id}/commission` | Commission the station into service through the full gate ladder | NetworkOperator |
| POST | `/charging-ports` | Install a dispenser/connector on a station | NetworkOperator |
| GET | `/charging-ports/{port_id}` | Fetch one charging port with both state dimensions | Any |
| GET | `/charging-ports/{id}/outage-events` | List outage events on this port, system-generated ones included | Any |
| PATCH | `/charging-ports/{port_id}` | Amend a port's payment-interoperability attributes | NetworkOperator |
| POST | `/charging-ports/{port_id}/terminal-certification` | Record the payment-terminal certification outcome | ComplianceAuditor |
| POST | `/charging-ports/{port_id}/retire` | Permanently retire a dispenser | NetworkOperator |
| POST | `/outage-events` | Ingest a remote-monitoring fault | NetworkOperator |
| GET | `/outage-events/{outage_event_id}` | Fetch one outage event with its exclusion bookkeeping | Any |
| POST | `/outage-events/{outage_event_id}/classify` | Classify the fault after triage | NetworkOperator |
| POST | `/outage-events/{outage_event_id}/exclusion-actions` | Request, approve, reject or revoke an uptime exclusion | NetworkOperator, ComplianceAuditor |
| POST | `/outage-events/{outage_event_id}/resolution-reviews` | Verify or reopen a resolved outage | NetworkOperator, ComplianceAuditor |
| POST | `/maintenance-dispatches` | Dispatch a technician to a classified fault inside a window | NetworkOperator |
| GET | `/maintenance-dispatches` | List dispatches, filtered and paginated | Any |
| GET | `/maintenance-dispatches/{dispatch_id}` | Fetch one dispatch with its response and hold figures | Any |
| POST | `/maintenance-dispatches/{dispatch_id}/progress` | Post a technician progress event | FieldTechnician |
| POST | `/maintenance-dispatches/{dispatch_id}/parts-hold` | Suspend the repair pending parts and recompute the promise | FieldTechnician |
| POST | `/maintenance-dispatches/{dispatch_id}/complete` | Close out the repair | FieldTechnician |
| POST | `/spare-parts` | Create a depot spare-part record | NetworkOperator |
| GET | `/spare-parts` | List depot spare parts with their encumbrance figures | Any |
| GET | `/spare-parts/{spare_part_id}` | Fetch one spare part | Any |
| POST | `/spare-parts/{spare_part_id}/restock` | Receive stock and promote backordered reservations | NetworkOperator |
| POST | `/part-reservations` | Earmark depot stock for a dispatch | NetworkOperator |
| GET | `/part-reservations` | List part reservations, released ones included | Any |
| GET | `/part-reservations/{reservation_id}` | Fetch one part reservation | Any |
| POST | `/part-reservations/{reservation_id}/disposition` | Consume or release a reservation | NetworkOperator, FieldTechnician |
| POST | `/uptime-reports` | Declare a reporting period for a station | NetworkOperator |
| GET | `/uptime-reports/{uptime_report_id}` | Fetch one report with its methodology and figures | Any |
| GET | `/uptime-reports/{id}/reimbursement-claims` | List claims filed against this report, superseded ones included | Any |
| POST | `/uptime-reports/{uptime_report_id}/compute-provisional` | Compute the provisional uptime variant | NetworkOperator |
| POST | `/uptime-reports/{uptime_report_id}/finalize` | Recompute under the final federal methodology and lock the auditor | ComplianceAuditor |
| POST | `/uptime-reports/{uptime_report_id}/submit` | Submit the finalised report to the programme | NetworkOperator |
| POST | `/uptime-reports/{uptime_report_id}/program-review` | Accept or return a submitted report | ProgramAdministrator |
| POST | `/reimbursement-claims` | File a claim against an accepted report | NetworkOperator |
| GET | `/reimbursement-claims/{claim_id}` | Fetch one claim with its snapshot and settled amounts | Any |
| POST | `/reimbursement-claims/{claim_id}/review` | Open the claim for adjudication and snapshot the tier | ProgramAdministrator |
| POST | `/reimbursement-claims/{claim_id}/decision` | Approve, withhold or deny the claim | ProgramAdministrator |
| POST | `/reimbursement-claims/{claim_id}/remediation` | File an uptime remediation credit and reopen adjudication | NetworkOperator |
| POST | `/customer-complaints` | Take a driver complaint with the disputed session's billing detail | CustomerSupportAgent |
| GET | `/customer-complaints` | List complaints, filtered and paginated | Any |
| GET | `/customer-complaints/{complaint_id}` | Fetch one complaint with both dimensions and the money split | Any |
| POST | `/customer-complaints/{complaint_id}/triage` | Link the complaint to an outage or dismiss it | CustomerSupportAgent |
| POST | `/customer-complaints/{complaint_id}/close` | Close a triaged complaint | CustomerSupportAgent |
| POST | `/customer-complaints/{complaint_id}/refund-requests` | File a session refund on the refund dimension | CustomerSupportAgent |
| POST | `/customer-complaints/{complaint_id}/refund-decisions` | Approve or deny the refund | ComplianceAuditor |
| POST | `/customer-complaints/{complaint_id}/refund-ledger-actions` | Settle or reverse the refund | CustomerSupportAgent, ComplianceAuditor |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_HOST_SITE_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_ASSIGNED_TECHNICIAN` | 403 Forbidden |
| `ERR_HOST_SITE_NOT_FOUND` | 404 Not Found |
| `ERR_STATION_NOT_FOUND` | 404 Not Found |
| `ERR_PORT_NOT_FOUND` | 404 Not Found |
| `ERR_OUTAGE_NOT_FOUND` | 404 Not Found |
| `ERR_DISPATCH_NOT_FOUND` | 404 Not Found |
| `ERR_SPARE_PART_NOT_FOUND` | 404 Not Found |
| `ERR_RESERVATION_NOT_FOUND` | 404 Not Found |
| `ERR_UPTIME_REPORT_NOT_FOUND` | 404 Not Found |
| `ERR_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_COMPLAINT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_SITE_CODE_DUPLICATE` | 409 Conflict |
| `ERR_STATION_CODE_DUPLICATE` | 409 Conflict |
| `ERR_DISPENSER_SERIAL_DUPLICATE` | 409 Conflict |
| `ERR_PART_NUMBER_DUPLICATE` | 409 Conflict |
| `ERR_STALE_PARENT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_TECHNICIAN_NOT_CERTIFIED` | 422 Unprocessable Entity |
| `ERR_OUTAGE_PORT_MISMATCH` | 409 Conflict |
| `ERR_CLAIM_LINE_PORT_MISMATCH` | 409 Conflict |
| `ERR_COMPLAINT_PORT_MISMATCH` | 409 Conflict |
| `ERR_COMPLAINT_OUTAGE_MISMATCH` | 409 Conflict |
| `ERR_DETECTED_AT_IN_FUTURE` | 422 Unprocessable Entity |
| `ERR_DETECTED_AT_BEFORE_PORT` | 422 Unprocessable Entity |
| `ERR_DISPATCH_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_DISPATCH_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_REPORTING_PERIOD_INVALID` | 422 Unprocessable Entity |
| `ERR_REPORTING_PERIOD_NOT_ELAPSED` | 422 Unprocessable Entity |
| `ERR_REPORTING_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_SESSION_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_INVALID_ACCESS_WINDOW` | 422 Unprocessable Entity |
| `ERR_HOST_AGREEMENT_NOT_EXECUTED` | 422 Unprocessable Entity |
| `ERR_POWER_UPGRADE_NOT_ENERGIZED` | 422 Unprocessable Entity |
| `ERR_PARKING_ENFORCEMENT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_PORT_COUNT_BELOW_DECLARED` | 422 Unprocessable Entity |
| `ERR_SITE_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_INTEROP_SCORE_BELOW_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_UPTIME_REPORT_NOT_ACCEPTED` | 409 Conflict |
| `ERR_STATION_NOT_SERVICEABLE` | 409 Conflict |
| `ERR_PORT_RETIRED` | 409 Conflict |
| `ERR_EXCLUSION_CAUSE_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_EXCLUSION_REVIEW_PENDING` | 409 Conflict |
| `ERR_NO_REPORTABLE_PORT_MINUTES` | 422 Unprocessable Entity |
| `ERR_REFUND_BASIS_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_REFUND_IN_FLIGHT` | 409 Conflict |
| `ERR_REFUND_EXCEEDS_SESSION_CHARGE` | 422 Unprocessable Entity |
| `ERR_SESSION_CHARGE_INVALID` | 422 Unprocessable Entity |
| `ERR_RESERVATION_QTY_INVALID` | 422 Unprocessable Entity |
| `ERR_CLAIM_LINE_ITEMS_EMPTY` | 422 Unprocessable Entity |
| `ERR_UPTIME_BELOW_APPROVAL_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_WITHHOLD_RATE_MISMATCH` | 422 Unprocessable Entity |
