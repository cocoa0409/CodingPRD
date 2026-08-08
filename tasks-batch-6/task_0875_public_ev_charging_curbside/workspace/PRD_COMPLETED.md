# Public EV-Charging & Curbside Program API — Product Requirements Document

## 1. Introduction

Municipal and private curbside electric-vehicle charging has grown from a novelty into regulated public infrastructure, and the organizations that operate it must simultaneously satisfy drivers, host-site landlords, field maintenance crews, and the grant agencies that reimburse construction and operation. This document specifies the Public EV-Charging & Curbside Program API — the system of record that ties together station inventory and live port status, time-of-use session pricing and idle occupancy fees, host-site agreements and their revenue-share negotiations, reservations and utilization, maintenance scheduling and uptime service levels, grant (for example, NEVI) compliance and rebate reconciliation, ADA accessibility, and end-of-period revenue settlement.

The platform is deliberately built around a set of overlapping temporal and financial concerns. Ports carry two independent status axes at once; sessions are priced against the hour of day at which they began and penalized for occupying a connector after charging completes; rebate claims are provisionally paid against operator-reported figures and then re-audited against measured downtime; and revenue is split between the host and the program on either a gross or a net basis. Because these calculations feed real money and regulatory attestations, the system is exacting about ordering, rounding, boundary inclusivity, and who is permitted to do what. The sections below define the global contracts first, then the business workflows, and finally the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, envelopes, and cross-cutting principles that govern every endpoint. Where a business workflow in Section 3 refers to "the standard rounding rule", "the ownership check", or "the stale-version rule", it is referring to the definitions established here.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the operational capacity under which they act. A request missing either header, or presenting an `X-User-Role` that is not one of the four recognized roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the acting role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles: `ProgramAdmin`, `HostOperator`, `FieldTechnician`, and `Driver`.

- A `ProgramAdmin` is the program operator. This is an opaque operator identity: `X-User-ID` is an operator identifier not tied to any persisted entity. The server may record it where a workflow calls for it — for example, capturing it as `submitted_by_user_id` on a rebate claim at submit — but it never compares that identifier to any entity's `id` for ownership purposes.
- A `HostOperator` represents a host or property owner and is an entity-backed identity. When `X-User-Role` is `HostOperator`, `X-User-ID` is the `id` of the acting `HostSite`. Ownership checks on any resource that references a host site compare the resource's site foreign key to `X-User-ID`: a `HostOperator` may counter only an agreement whose `site_id` equals `X-User-ID`, and may read only its own site and that site's agreements, stations, and revenue statements. An ownership failure is reported as `ERR_NOT_RESOURCE_OWNER` (HTTP 403).
- A `FieldTechnician` is a field maintenance operator with an opaque identity: `X-User-ID` is an operator identifier not tied to any persisted entity, used for authorization but never for ownership comparison.
- A `Driver` is an EV driver with an opaque identity. `X-User-ID` is an opaque driver identifier not tied to any persisted entity; the server records it as the `driver_id` on the sessions and reservations the driver creates, and ownership checks compare that stored `driver_id` to `X-User-ID` rather than treating `X-User-ID` as any entity's `id`. A driver may stop, cancel, confirm, or check in only against a session or reservation whose `driver_id` equals its own `X-User-ID`, failing otherwise with `ERR_NOT_RESOURCE_OWNER`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; when omitted it defaults to 10, and it is constrained to a minimum of 1 and a maximum of 100. A supplied `limit` below 1 or above 100 is clamped into that range rather than rejected, and a `limit` or `offset` that is not a valid integer falls back to its default. The `offset` parameter is the number of items to skip and defaults to 0; a negative `offset` is treated as 0.

Unless a specific workflow states otherwise, list endpoints return resources sorted by their creation timestamp, `created_at`, in ascending order, ties on `created_at` broken by the order in which the resources were created (insertion order), never by `id`. Every list response includes `limit`, `offset`, `total_count`, and `has_more` inside the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every resource in this system is a top-level entity, and all of them carry the standard system-managed fields. `id` is a unique, server-minted UUID with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. `updated_at` is an ISO 8601 UTC timestamp recording the most recent modification, refreshed on every mutation. `version` is an integer that begins at 1 on creation and increments by one on every mutation of the resource. All eleven resource types — host sites, host agreements, grant programs, stations, ports, charging sessions, reservations, maintenance windows, work orders, rebate claims, and revenue statements — carry all four of these fields; none is create-only.

Timestamps written by the system as the result of a business event — a session's `started_at`, `stopped_at`, and `unplugged_at`; a work order's `opened_at` and `resolved_at`; a port's `oos_opened_at` — are always drawn from the logical clock described in Section 2.5, and are rendered in the same ISO 8601 UTC format with three fractional digits, echoing the exact instant the clock was set to rather than any wall-clock reading.

### 2.5. The Logical Clock

All server-assigned instants come from a logical clock rather than the host machine's wall clock. At server startup the clock reads exactly `2026-05-01T00:00:00Z`, and until a `ProgramAdmin` explicitly advances it, every system timestamp reflects that default; the server never falls back to wall-clock time. An administrative test-driving capability sets the logical clock to a supplied `to_iso8601` instant, after which all subsequently minted timestamps — session and work-order events, out-of-service markers, and the "current clock" used in service-level and audit comparisons — read from the new value. Because downtime, idle, and SLA math all depend on this clock, tests advance it deliberately between steps.

### 2.6. Monetary Values, Counts, and Precision

All monetary amounts in the system are integer counts of whole cents; there are no fractional-cent fields. Wherever a calculation multiplies a rate by a quantity and the mathematical result is not already whole cents, the system rounds to the nearest whole cent using the round-half-up convention (a value exactly halfway between two cents rounds up). Unless a rule explicitly directs otherwise, this rounding is applied per session or per unit before any summation across sessions — never by summing exact values and rounding once at the end. The single exception in the opposite direction is uptime, which is a percentage rounded half-up to two decimal places. Duration-derived integers such as `idle_minutes` are floored, not rounded.

Two per-site totals are treated as conserved ledger quantities that must always equal the sum of their constituent parts: a host site's `lifetime_gross_revenue_cents` and a station's `available_ports`. Every operation that could change either quantity must adjust it so it remains exactly reconstructable from the underlying sessions or ports.

### 2.7. Optimistic Concurrency Control

Two create operations guard a parent resource with optimistic concurrency control, and both use the stale-version model rather than any time-of-arrival model.

Creating a rebate claim snapshots the target station's commissioned configuration, so the create request must carry `expected_station_version` holding the client's last observed `version` of that `Station`. If the station's `version` has advanced since the client last read it — because a prior claim create bumped it, or the station was recommissioned or reconfigured — the create is rejected with `ERR_STALE_VERSION` (HTTP 412); the client must re-read the station and retry against its current `version`. A successful create increments the station's `version` by one, so the new claim supersedes any prior draft claim for the same period.

Generating a revenue statement snapshots the host site's session ledger for the period, so the create request must carry `expected_site_version` holding the client's last observed `version` of that `HostSite`. If the site's `version` has advanced since the client last read it — because a prior statement generation bumped it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412); the client must re-read the site's current ledger and regenerate against it. A successful create increments the host site's `version` by one, and the new statement supersedes any prior draft statement for the period.

Endpoints that are not one of these two creates do not accept a version field and perform no such check.

### 2.8. Nested Retrieval and Referential Integrity

The only nested read path in the system lists a station's ports. For any request whose path names more than one resource, existence is validated strictly left-to-right, and the first identifier that does not resolve determines the 404 returned. Each entity type has its own not-found code — for example `ERR_STATION_NOT_FOUND`, `ERR_PORT_NOT_FOUND`, `ERR_HOST_SITE_NOT_FOUND`, `ERR_HOST_AGREEMENT_NOT_FOUND`, `ERR_GRANT_PROGRAM_NOT_FOUND`, `ERR_CHARGING_SESSION_NOT_FOUND`, `ERR_RESERVATION_NOT_FOUND`, `ERR_MAINTENANCE_WINDOW_NOT_FOUND`, `ERR_WORK_ORDER_NOT_FOUND`, `ERR_REBATE_CLAIM_NOT_FOUND`, and `ERR_REVENUE_STATEMENT_NOT_FOUND` — and the code raised names the resource type of the missing identifier.

Beyond path identifiers, create requests that carry a foreign-key reference in their body — a `site_id`, `grant_id`, `station_id`, or `port_id` — must resolve those references to an existing row, and a dangling reference is likewise reported with the corresponding not-found code for the referenced type. Missing required fields, wrong types, and invalid enum values are rejected with `ERR_VALIDATION` (HTTP 400).

### 2.9. Cascading State Propagation and Consistency

Many operations mutate more than one resource. Whenever the system automatically transitions a child because a parent changed, each affected resource whose own stored state the cascade changes independently records the mutation by refreshing its `updated_at` and incrementing its `version`. A station's `station_count` on its host site, a station's `total_ports` and `available_ports`, and a host site's `lifetime_gross_revenue_cents` are all derived quantities that the system keeps current as the rows beneath them change; the three port-count fields are recomputed from the underlying ports on every read and therefore do not by themselves bump the owning resource's `version` or `updated_at` (adding a port or changing a port's occupancy leaves the station's `version` untouched), and `lifetime_gross_revenue_cents` is adjusted in place whenever a session finalizes or voids without incrementing the host site's `version` or refreshing its `updated_at` — only a direct mutation of the host site or the optimistic-concurrency-guarded revenue-statement generation advances the site's `version`. The specific cascades — agreement termination decommissioning stations and their ports and aborting active sessions, a critical work order knocking a port out of service, maintenance suspending and later restoring a station — are described in their respective Section 3 workflows, and every branch of each cascade is authoritative, not best-effort.

### 2.10. Validation Ordering and Precedence

When several checks could reject the same request, they are evaluated in a fixed order so the returned error is deterministic. Authentication of the headers comes first (`ERR_UNAUTHENTICATED`), then role authorization (`ERR_UNAUTHORIZED`), then existence of every resource named in the path (the appropriate not-found code, left-to-right), then existence of referenced foreign-key bodies (their not-found codes). Ownership is checked next (`ERR_NOT_RESOURCE_OWNER`), followed by whether the target resource is in a state from which the requested transition is legal (`ERR_INVALID_STATE`). Only after these structural gates do the domain-specific business rules run: the active-agreement requirement at commission (`ERR_AGREEMENT_NOT_ACTIVE`); the ADA and four-eyes safety gates (`ERR_ADA_PORT_REQUIRED`, `ERR_SEGREGATION_OF_DUTIES`); the temporal-conflict checks (`ERR_RESERVATION_OVERLAP`, `ERR_MAINTENANCE_WINDOW_OVERLAP`, `ERR_INVALID_WINDOW`, `ERR_INVALID_PERIOD`); the port-availability and configuration checks (`ERR_PORT_OUT_OF_SERVICE`, `ERR_PORT_NOT_AVAILABLE`, `ERR_INSUFFICIENT_PORTS`, `ERR_ENERGY_INVALID`); the rebate compliance gate (`ERR_UPTIME_BELOW_THRESHOLD`); and finally the optimistic-concurrency check (`ERR_STALE_VERSION`). A rule earlier in this order always masks a rule later in it.

## 3. Business Logic & Workflows

### 3.1. Host Sites and the Host-Agreement Negotiation

The program's commercial relationships begin with a **host site** — a curbside or property location created by a `ProgramAdmin` with a `name`, an `address`, a `state_code` such as CA, and a `revenue_share_pct` expressed as a fraction between 0 and 1 (for example, 0.15 for a fifteen-percent host share). A site may declare `ada_required`, defaulting to false, which signals that at least one ADA-accessible port is legally required per station at this site. For settlement on a net basis the site also carries a payment-processor fee profile: `transaction_fee_pct`, a fraction defaulting to 0.029, and `transaction_fee_flat_cents`, a flat per-session amount defaulting to 30. On creation the site's running ledger `lifetime_gross_revenue_cents` starts at 0, its derived `station_count` starts at 0, and its `version` starts at 1. A `HostOperator` may read only its own site; a `ProgramAdmin` may read any.

Before a site's stations can operate, the program and the host must agree on terms through a **host agreement**. A `ProgramAdmin` drafts an agreement against a `site_id` with a `term_start_date`, a `term_end_date`, and a `proposed_revenue_share_pct`; it is born in `DRAFT` with `round_count` at 0 and `counter_revenue_share_pct` unset. The negotiation is a cycle. The program moving an agreement from `DRAFT` to `PROPOSED` — and, later, re-proposing from `COUNTERED` back to `PROPOSED`, optionally supplying a fresh `proposed_revenue_share_pct` — advances it into the host's court. The host, acting as the owning `HostOperator`, counters a `PROPOSED` agreement into `COUNTERED`, which records the supplied `counter_revenue_share_pct` and increments `round_count` by one; a counter attempted by an operator whose `X-User-ID` is not the agreement's `site_id` is rejected with `ERR_NOT_RESOURCE_OWNER`. This `PROPOSED` ↔ `COUNTERED` loop may repeat any number of rounds.

The program activates a `PROPOSED` agreement into `ACTIVE`, but only when no other `ACTIVE` host agreement already exists for the same `site_id`; a second active agreement for one site is refused with `ERR_INVALID_STATE`. Activating from any state other than `PROPOSED` is likewise an `ERR_INVALID_STATE`. Terminating an `ACTIVE` agreement moves it to the terminal `TERMINATED` state and triggers a three-level cascade: every `Station` for that `site_id` whose `operational_status` is `PENDING`, `COMMISSIONED`, or `SUSPENDED` is driven to `DECOMMISSIONED`; each such station's ports whose `operational_status` is `IN_SERVICE` are driven to `OUT_OF_SERVICE` with `oos_opened_at` set to the current clock instant; and each such port's `ACTIVE` charging session is driven to `ABORTED` with its `final_cost_cents` set to 0 and no revenue posted. Legal states for an agreement are `DRAFT`, `PROPOSED`, `COUNTERED`, `ACTIVE`, and `TERMINATED`.

### 3.2. Grant Programs, Stations, and Commissioning

A **grant program** captures the eligibility and reimbursement terms of a funding source such as NEVI. A `ProgramAdmin` creates one with a `name`, a `program_code`, a `min_uptime_pct` (the minimum monthly uptime percent, on a 0-to-100 scale, required for compliance — for example 97.0), a `min_ports` count and a `min_power_kw` rating that a station must meet to qualify, a `reimbursement_rate_cents_per_kwh`, and a per-claim `reimbursement_cap_cents`.

A **station** is created by a `ProgramAdmin` against a `site_id`, with an optional `grant_id` (null when the station is not enrolled in a grant), a display `name`, and an optional station-level `ada_accessible` flag defaulting to false. It begins in `PENDING` with derived `total_ports` and `available_ports` both at 0; those counts are the number of ports on the station and, respectively, the number of its ports that are simultaneously `IN_SERVICE` on the operational axis and `AVAILABLE` on the occupancy axis. Legal station states are `PENDING`, `COMMISSIONED`, `SUSPENDED`, and `DECOMMISSIONED`.

Commissioning a `PENDING` station into `COMMISSIONED` is gated by three business rules evaluated after the structural checks. First, an `ACTIVE` host agreement must exist for the station's `site_id`, or the request is refused with `ERR_AGREEMENT_NOT_ACTIVE`. Second, if the site declares `ada_required` or the station carries a `grant_id`, the station must have at least one port whose `ada_accessible` is true, failing which the request is refused with `ERR_ADA_PORT_REQUIRED`. Third, if a `grant_id` is present, the station's `total_ports` must be at least the grant's `min_ports`, or the request is refused with `ERR_INSUFFICIENT_PORTS`. Commissioning from any non-`PENDING` state is an `ERR_INVALID_STATE`.

Decommissioning drives a station from `PENDING`, `COMMISSIONED`, or `SUSPENDED` to the terminal `DECOMMISSIONED` state. When decommissioning a station that was commissioned or suspended, each of its ports whose `operational_status` is `IN_SERVICE` is driven to `OUT_OF_SERVICE`. Decommissioning also occurs as part of the agreement-termination cascade described above.

### 3.3. Ports and Their Dual Status Axes

A **port** is a single connector, created by a `ProgramAdmin` against a `station_id` with a `connector_type` — one of `CCS1`, `CCS2`, `NACS`, or `CHADEMO` — a rated `power_kw`, and an optional `ada_accessible` flag defaulting to false. Every port tracks two independent status axes at once. The operational axis, `operational_status`, is `IN_SERVICE` by default and can also be `OUT_OF_SERVICE`. The occupancy axis, `occupancy_status`, is `AVAILABLE` by default and can also be `RESERVED` or `OCCUPIED`. These axes move independently: a port can be `OUT_OF_SERVICE` while its occupancy is being freed, and an `IN_SERVICE` port cycles through occupancy states as sessions and reservations come and go. The `oos_opened_at` field records the logical-clock instant the port last entered `OUT_OF_SERVICE` and is null whenever the port is `IN_SERVICE`.

A `FieldTechnician` takes a port out of service, setting `operational_status` to `OUT_OF_SERVICE`, stamping `oos_opened_at` with the current instant, and — as a cascade — aborting any `ACTIVE` charging session on that port, which in turn frees the port's `occupancy_status` back to `AVAILABLE`. The system also drives a port to `OUT_OF_SERVICE` on its own when a critical work order opens, when the station is decommissioned, or as part of agreement termination. Returning a port to service moves `operational_status` back to `IN_SERVICE` and clears `oos_opened_at` to null, but only when no `OPEN` `CRITICAL` work order remains on the port; otherwise the request is refused with `ERR_INVALID_STATE`.

On the occupancy axis, starting a session or checking in a reservation moves an `AVAILABLE` port to `OCCUPIED`; finalizing a session or aborting one moves an `OCCUPIED` port back to `AVAILABLE`; confirming a reservation moves an `AVAILABLE` port to `RESERVED`; cancelling a confirmed reservation moves a `RESERVED` port back to `AVAILABLE`; and checking in a reserved port moves it from `RESERVED` to `OCCUPIED`. Occupying a port for a new session or reservation requires the port to be `IN_SERVICE`; an attempt on an out-of-service port is refused with `ERR_PORT_OUT_OF_SERVICE`. Every one of these occupancy changes keeps the station's `available_ports` count exact.

### 3.4. Charging Sessions: Pricing, Idle Fees, and the Ledger

A `Driver` starts a **charging session** by supplying a `port_id` and a `driver_id`; the session is created `ACTIVE`, its `started_at` stamped with the current clock, and the target port moved to `OCCUPIED`. The port must be `IN_SERVICE` (else `ERR_PORT_OUT_OF_SERVICE`) and `AVAILABLE` (else `ERR_PORT_NOT_AVAILABLE`). Legal session states are `ACTIVE`, `STOPPED`, `FINALIZED`, `VOIDED`, and `ABORTED`.

**Stopping.** The owning driver stops an `ACTIVE` session, reporting delivered `energy_kwh`, which must be greater than 0 (else `ERR_ENERGY_INVALID`); a stop attempted by a driver who is not the session's owner is refused with `ERR_NOT_RESOURCE_OWNER`. Stopping stamps `stopped_at` with the current instant, moves the session to `STOPPED`, and prices the energy. First the system derives the time-of-use bucket `tou_period` from the UTC hour of `started_at`: the hour is `PEAK` when it is at least 16 and before 21, `OFFPEAK` when it is at least 0 and before 7, and `SHOULDER` at every other hour. The per-kWh base rate follows the bucket — 48 cents for `PEAK`, 36 cents for `SHOULDER`, and 24 cents for `OFFPEAK`. A demand surcharge of 5 cents per kWh is added to the base rate when, and only when, the session's port has a `power_kw` of at least 150; below that rating no surcharge applies. The raw energy charge is the delivered `energy_kwh` multiplied by the sum of the base rate and any demand surcharge, in cents; `energy_cost_cents` is that raw amount rounded half-up to a whole cent, then capped so it never exceeds 50000 cents. The flat `session_fee_cents` is 100. At stop the system records `preliminary_cost_cents` as the sum of `energy_cost_cents` and `session_fee_cents`, before any idle fee is known.

**Finalizing.** A `ProgramAdmin` finalizes a `STOPPED` session, stamping `unplugged_at` with the current instant and computing the idle penalty. The `idle_minutes` are the whole minutes between `stopped_at` and `unplugged_at`, computed as the elapsed seconds divided by 60 and floored to an integer. An idle fee applies only when `idle_minutes` is strictly greater than the 10-minute grace allowance; when it is, `idle_fee_cents` is the number of minutes beyond the grace — that is, `idle_minutes` minus 10 — multiplied by 40 cents per minute, then capped so it never exceeds 3000 cents. When `idle_minutes` is 10 or fewer, `idle_fee_cents` is 0. The `final_cost_cents` is the sum of `energy_cost_cents`, `session_fee_cents`, and `idle_fee_cents`. Finalizing also frees the port's `occupancy_status` to `AVAILABLE` and posts revenue to the ledger: the host site's `lifetime_gross_revenue_cents` increases by the session's `final_cost_cents`.

**Voiding.** A `ProgramAdmin` may void a `FINALIZED` session into `VOIDED`, which reverses the ledger posting by decreasing the host site's `lifetime_gross_revenue_cents` by that session's `final_cost_cents`, returning the ledger exactly to its pre-finalize value.

**Aborting.** A session is never aborted by a client directly. When a port is taken out of service — by a field technician, by a critical work order, by station decommissioning, or by agreement termination — its `ACTIVE` session is driven to the terminal `ABORTED` state with `final_cost_cents` set to 0 and no revenue posted, and the port's `occupancy_status` is freed to `AVAILABLE`.

### 3.5. Reservations

A `Driver` creates a **reservation** by supplying a `port_id`, a `driver_id`, a `window_start`, and a `window_end`, where `window_end` must be later than `window_start` (else `ERR_INVALID_WINDOW`); the reservation is born `PENDING`. Legal reservation states are `PENDING`, `CONFIRMED`, `FULFILLED`, and `CANCELLED`.

Confirming a `PENDING` reservation into `CONFIRMED` holds the port: it requires the port to be `IN_SERVICE` (else `ERR_PORT_OUT_OF_SERVICE`) and `AVAILABLE` (else `ERR_PORT_NOT_AVAILABLE`), and it requires that no existing `CONFIRMED` reservation on the same port cover an overlapping window. Overlap is judged on half-open intervals `[window_start, window_end)`: two windows conflict when one starts strictly before the other ends and vice versa, so windows that merely touch at an endpoint do not conflict. A genuine overlap is refused with `ERR_RESERVATION_OVERLAP`. On confirmation the port's `occupancy_status` moves to `RESERVED`. Checking in a `CONFIRMED` reservation moves it to the terminal `FULFILLED` state and the port to `OCCUPIED`.

Cancelling a reservation moves it to the terminal `CANCELLED` state. Cancelling a `PENDING` reservation has no port effect, but cancelling a `CONFIRMED` reservation releases its hold, returning the port's `occupancy_status` to `AVAILABLE` and restoring the station's `available_ports`. Ownership applies throughout: a driver may confirm, cancel, or check in only a reservation whose `driver_id` is its own `X-User-ID`, failing otherwise with `ERR_NOT_RESOURCE_OWNER`.

### 3.6. Maintenance Windows, Work Orders, and Service Levels

A `ProgramAdmin` schedules a **maintenance window** against a `station_id` with a `window_start`, a `window_end` (which must exceed `window_start`, else `ERR_INVALID_WINDOW`), and a `reason`; it is born `SCHEDULED`. A new window is refused with `ERR_MAINTENANCE_WINDOW_OVERLAP` when its closed interval `[window_start, window_end]` falls within 60 minutes of another `SCHEDULED` or `IN_PROGRESS` window on the same station — that is, consecutive windows on one station must be separated by at least an hour of clearance. Legal maintenance states are `SCHEDULED`, `IN_PROGRESS`, and `COMPLETED`.

A `FieldTechnician` starts a `SCHEDULED` window into `IN_PROGRESS`, which requires the station to be `COMMISSIONED` (else `ERR_INVALID_STATE`) and, as a side effect, suspends the station by moving its `operational_status` to `SUSPENDED`. Completing an `IN_PROGRESS` window into `COMPLETED` restores the station by moving its `operational_status` back to `COMMISSIONED`.

A `FieldTechnician` opens a **work order** against a `port_id` with a `severity` — one of `LOW`, `MEDIUM`, or `CRITICAL` — and a `description`; it is born `OPEN` with `opened_at` stamped at the current instant. The service-level due time `sla_due_at` is `opened_at` plus a severity-dependent allowance: 4 hours for `CRITICAL`, 24 hours for `MEDIUM`, and 72 hours for `LOW`. The `sla_breached` flag is true when the breach reference instant is strictly later than `sla_due_at`, where the breach reference is `resolved_at` once the order is `RESOLVED` and the current clock instant while it is still `OPEN`. Opening a `CRITICAL` work order triggers a three-level cascade: the port's `operational_status` is driven to `OUT_OF_SERVICE`, its `ACTIVE` charging session is driven to `ABORTED`, and that abort frees the port's `occupancy_status` to `AVAILABLE`. Resolving an `OPEN` work order into `RESOLVED` stamps `resolved_at` at the current instant and recomputes `sla_breached`. Legal work-order states are `OPEN` and `RESOLVED`.

### 3.7. Rebate Claims: Compliance, Audit, and Four-Eyes Approval

A **rebate claim** reconciles a station's operation against a grant. A `ProgramAdmin` creates one against a `station_id` and `grant_id` with a `period_start`, a `period_end` (which must exceed `period_start`, else `ERR_INVALID_PERIOD`), an operator-reported `reported_energy_kwh`, and an operator-reported `reported_uptime_pct` on a 0-to-100 scale. Because the create snapshots the station's configuration, it also carries `expected_station_version` and is subject to the stale-version rule of Section 2.7. The claim is born `DRAFT` with `compliance_status` at `PENDING`; its `measured_uptime_pct`, `estimated_amount_cents`, `audited_amount_cents`, and `submitted_by_user_id` are unset or 0 until later stages. Legal claim states are `DRAFT`, `SUBMITTED`, `AUDITED`, `APPROVED`, and `REJECTED`.

**Submit.** Submitting a `DRAFT` claim into `SUBMITTED` passes a compliance gate: the `reported_uptime_pct` must be at least the grant's `min_uptime_pct` (a value exactly equal to the minimum passes), or the submission is refused with `ERR_UPTIME_BELOW_THRESHOLD`. On success the system sets the provisional `estimated_amount_cents` to the reported delivered energy `reported_energy_kwh` multiplied by the grant's `reimbursement_rate_cents_per_kwh`, rounded half-up to a whole cent and then capped so it never exceeds the grant's `reimbursement_cap_cents`; it sets `compliance_status` to `COMPLIANT`; and it records `submitted_by_user_id` as the submitting administrator's `X-User-ID`. The estimated amount is always positive once the reported-uptime gate passes and ignores any audited downtime.

**Audit.** Auditing a `SUBMITTED` claim into `AUDITED` recomputes uptime from measured downtime. The period length in minutes is the whole span between `period_start` and `period_end`. The critical downtime is the sum, over every `CRITICAL` work order on a port belonging to the claim's station that has a non-null `resolved_at` and whose open interval `[opened_at, resolved_at)` intersects the claim period `[period_start, period_end)`, of the overlap minutes — that is, the minutes from the later of `opened_at` and `period_start` up to the earlier of `resolved_at` and `period_end`. The `measured_uptime_pct` is 100 times the quantity one minus the ratio of critical downtime minutes to period minutes, rounded half-up to two decimal places and clamped to the range 0 through 100. If `measured_uptime_pct` is at least the grant's `min_uptime_pct`, the `audited_amount_cents` is set equal to `estimated_amount_cents` and `compliance_status` stays `COMPLIANT`; otherwise `audited_amount_cents` collapses to 0 and `compliance_status` becomes `NON_COMPLIANT`. This is the deliberate asymmetry between the two amounts: a claim that cleared the reported-uptime gate at submit can still collapse to a zero audited amount when measured downtime pulls uptime below the minimum.

**Approve and reject.** Approving an `AUDITED` claim into the terminal `APPROVED` state enforces a four-eyes segregation of duties: the approving administrator's `X-User-ID` must differ from `submitted_by_user_id`, or the approval is refused with `ERR_SEGREGATION_OF_DUTIES`. A claim may instead be rejected into the terminal `REJECTED` state from either `SUBMITTED` or `AUDITED`.

### 3.8. Revenue Statements and Reconciliation

At period end a `ProgramAdmin` generates a **revenue statement** for a site, reconciling the host's and program's shares of session revenue. The statement is created against a `site_id` with a `period_start`, a `period_end` (which must exceed `period_start`, else `ERR_INVALID_PERIOD`), and a `basis` that is either `GROSS` or `NET`. Because generation snapshots the site's ledger, the request carries `expected_site_version` and is subject to the stale-version rule of Section 2.7; a successful generation increments the site's `version` by one. The statement is born `DRAFT` and later moves to the terminal `FINALIZED` state. Legal statement states are `DRAFT` and `FINALIZED`.

The reconciliation considers the set of included sessions: every charging session whose `status` is `FINALIZED`, whose port's station has `site_id` equal to the statement's site, and whose `started_at` falls within the half-open period `[period_start, period_end)`. These sessions are processed in a deterministic order — by `started_at` ascending, breaking ties by `created_at` ascending, never by `id`. The `session_count` is the number of such sessions. The `gross_revenue_cents` is the sum of their `final_cost_cents`. The `transaction_fees_cents` is computed per session and summed: for each session it is that session's `final_cost_cents` multiplied by the site's `transaction_fee_pct` and rounded half-up to a whole cent, plus the site's flat `transaction_fee_flat_cents`.

The `host_share_cents` is where the two bases diverge, and in both cases the per-session amount is rounded half-up before summation — the rounding is applied per session, never by summing exact values and rounding once. Under the `GROSS` basis, the host share is the sum over the included sessions of each session's `final_cost_cents` multiplied by the site's `revenue_share_pct`, rounded half-up per session. Under the `NET` basis, the host share is the sum over the included sessions of the same `revenue_share_pct` multiplied not by the full `final_cost_cents` but by the amount net of that session's processor fee — that is, `final_cost_cents` minus the quantity (`final_cost_cents` times `transaction_fee_pct`, rounded half-up, plus `transaction_fee_flat_cents`) — again rounded half-up per session. Because the net basis shrinks each session's base by the processor fee, it yields a strictly lower host share than the gross basis whenever fees are positive. Finally, the `program_share_cents` is the `gross_revenue_cents` minus the `host_share_cents` minus the `transaction_fees_cents`. Finalizing a `DRAFT` statement simply moves it to `FINALIZED`.

## 4. Endpoint Definitions

Operations that create a new stand-alone resource return `201 Created`. Operations that modify an existing resource — including all state-transition actions — return `200 OK`. All list and single-read operations return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/host-sites` | Create a host site | ProgramAdmin |
| GET | `/host-sites/{id}` | Get a host site (HostOperator only its own) | ProgramAdmin, HostOperator |
| POST | `/host-agreements` | Create a host agreement (DRAFT) | ProgramAdmin |
| GET | `/host-agreements/{id}` | Get a host agreement | ProgramAdmin, HostOperator |
| GET | `/host-agreements` | List host agreements (filter by site) | ProgramAdmin, HostOperator |
| POST | `/host-agreements/{id}/propose` | Program proposes (DRAFT/COUNTERED → PROPOSED) | ProgramAdmin |
| POST | `/host-agreements/{id}/counter` | Host counters (PROPOSED → COUNTERED) | HostOperator |
| POST | `/host-agreements/{id}/activate` | Program activates (PROPOSED → ACTIVE) | ProgramAdmin |
| POST | `/host-agreements/{id}/terminate` | Terminate (ACTIVE → TERMINATED); cascades | ProgramAdmin |
| POST | `/grant-programs` | Create a grant program | ProgramAdmin |
| GET | `/grant-programs/{id}` | Get a grant program | ProgramAdmin, HostOperator |
| POST | `/stations` | Create a station (PENDING) | ProgramAdmin |
| GET | `/stations/{id}` | Get a station | ProgramAdmin, HostOperator, FieldTechnician |
| GET | `/stations` | List stations (filter by site or grant) | ProgramAdmin, HostOperator |
| GET | `/stations/{id}/ports` | List a station's ports | ProgramAdmin, HostOperator, FieldTechnician |
| POST | `/stations/{id}/commission` | Commission a station (PENDING → COMMISSIONED) | ProgramAdmin |
| POST | `/stations/{id}/decommission` | Decommission a station (→ DECOMMISSIONED) | ProgramAdmin |
| POST | `/ports` | Create a port on a station | ProgramAdmin |
| GET | `/ports/{id}` | Get a port | ProgramAdmin, HostOperator, FieldTechnician, Driver |
| POST | `/ports/{id}/out-of-service` | Take a port OUT_OF_SERVICE | FieldTechnician |
| POST | `/ports/{id}/in-service` | Return a port IN_SERVICE | FieldTechnician |
| POST | `/charging-sessions` | Start a charging session (ACTIVE) | Driver |
| GET | `/charging-sessions/{id}` | Get a charging session | ProgramAdmin, Driver |
| GET | `/charging-sessions` | List charging sessions (filter by port or driver) | ProgramAdmin, Driver |
| POST | `/charging-sessions/{id}/stop` | Stop charging (ACTIVE → STOPPED); report energy | Driver |
| POST | `/charging-sessions/{id}/finalize` | Finalize (STOPPED → FINALIZED); idle + ledger | ProgramAdmin |
| POST | `/charging-sessions/{id}/void` | Void a finalized session (FINALIZED → VOIDED) | ProgramAdmin |
| POST | `/reservations` | Create a reservation (PENDING) | Driver |
| GET | `/reservations/{id}` | Get a reservation | ProgramAdmin, Driver |
| GET | `/reservations` | List reservations (filter by port or driver) | ProgramAdmin, Driver |
| POST | `/reservations/{id}/confirm` | Confirm a reservation (PENDING → CONFIRMED) | Driver |
| POST | `/reservations/{id}/cancel` | Cancel a reservation (→ CANCELLED) | Driver |
| POST | `/reservations/{id}/check-in` | Check in (CONFIRMED → FULFILLED) | Driver |
| POST | `/maintenance-windows` | Schedule a maintenance window (SCHEDULED) | ProgramAdmin |
| GET | `/maintenance-windows/{id}` | Get a maintenance window | ProgramAdmin, FieldTechnician |
| GET | `/maintenance-windows` | List maintenance windows (filter by station) | ProgramAdmin, FieldTechnician |
| POST | `/maintenance-windows/{id}/start` | Start maintenance (SCHEDULED → IN_PROGRESS) | FieldTechnician |
| POST | `/maintenance-windows/{id}/complete` | Complete maintenance (IN_PROGRESS → COMPLETED) | FieldTechnician |
| POST | `/work-orders` | Open a work order (OPEN); CRITICAL cascades | FieldTechnician |
| GET | `/work-orders/{id}` | Get a work order | ProgramAdmin, FieldTechnician |
| GET | `/work-orders` | List work orders (filter by port) | ProgramAdmin, FieldTechnician |
| POST | `/work-orders/{id}/resolve` | Resolve a work order (OPEN → RESOLVED) | FieldTechnician |
| POST | `/rebate-claims` | Create a rebate claim (DRAFT); OCC on Station | ProgramAdmin |
| GET | `/rebate-claims/{id}` | Get a rebate claim | ProgramAdmin |
| GET | `/rebate-claims` | List rebate claims (filter by station or grant) | ProgramAdmin |
| POST | `/rebate-claims/{id}/submit` | Submit (DRAFT → SUBMITTED); compliance gate | ProgramAdmin |
| POST | `/rebate-claims/{id}/audit` | Audit (SUBMITTED → AUDITED); measured uptime | ProgramAdmin |
| POST | `/rebate-claims/{id}/approve` | Approve (AUDITED → APPROVED); four-eyes | ProgramAdmin |
| POST | `/rebate-claims/{id}/reject` | Reject (SUBMITTED/AUDITED → REJECTED) | ProgramAdmin |
| POST | `/revenue-statements` | Generate a revenue statement (DRAFT); OCC on Site | ProgramAdmin |
| GET | `/revenue-statements/{id}` | Get a revenue statement | ProgramAdmin, HostOperator |
| GET | `/revenue-statements` | List revenue statements (filter by site) | ProgramAdmin, HostOperator |
| POST | `/revenue-statements/{id}/finalize` | Finalize a revenue statement (DRAFT → FINALIZED) | ProgramAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock (test-driving) | ProgramAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_HOST_SITE_NOT_FOUND` | 404 Not Found |
| `ERR_HOST_AGREEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_GRANT_PROGRAM_NOT_FOUND` | 404 Not Found |
| `ERR_STATION_NOT_FOUND` | 404 Not Found |
| `ERR_PORT_NOT_FOUND` | 404 Not Found |
| `ERR_CHARGING_SESSION_NOT_FOUND` | 404 Not Found |
| `ERR_RESERVATION_NOT_FOUND` | 404 Not Found |
| `ERR_MAINTENANCE_WINDOW_NOT_FOUND` | 404 Not Found |
| `ERR_WORK_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_REBATE_CLAIM_NOT_FOUND` | 404 Not Found |
| `ERR_REVENUE_STATEMENT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_ADA_PORT_REQUIRED` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_RESERVATION_OVERLAP` | 409 Conflict |
| `ERR_MAINTENANCE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_INVALID_WINDOW` | 409 Conflict |
| `ERR_INVALID_PERIOD` | 409 Conflict |
| `ERR_PORT_OUT_OF_SERVICE` | 409 Conflict |
| `ERR_PORT_NOT_AVAILABLE` | 409 Conflict |
| `ERR_INSUFFICIENT_PORTS` | 422 Unprocessable Entity |
| `ERR_ENERGY_INVALID` | 422 Unprocessable Entity |
| `ERR_UPTIME_BELOW_THRESHOLD` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
