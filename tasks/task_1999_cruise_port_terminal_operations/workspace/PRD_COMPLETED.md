# Cruise Port Terminal Ops API — Product Requirements Document

## 1. Introduction

A cruise terminal lives and dies by the turnaround: within a single day a vessel must be berthed, thousands of debarking passengers cleared through customs and baggage claim, thousands of embarking passengers screened and boarded, provisions loaded and waste offloaded, ground transport dispatched in waves, and the vessel billed and released back to sea. Each of these threads is owned by a different organization — the port authority, the harbormaster, terminal floor staff, the shipping line's agent, customs liaison officers, and the port's finance office — and each thread can invalidate another. A storm system can freeze the berth schedule; a customs hold can strand passengers mid-flow; a lost berth window can void a provisioning contract.

This document specifies the Cruise Port Terminal Operations API, a single system of record for that day. All endpoints are mounted under the `/port-ops` prefix. The API is built around three governing ideas. First, every terminal carries a live operating **posture** — derived from weather advisories and berth occupancy — that gates what may be approved, confirmed, dispatched, or departed at any moment. Second, billing is two-layered: a provisional invoice tracks the call as it evolves and a final invoice is struck from actuals at close, and the two can legitimately diverge. Third, time itself is a governed input: every time-dependent rule in the system evaluates against a logical clock rather than the wall clock, so that operations are deterministic and replayable. The sections that follow define the system-wide contracts first, then the business workflows that scatter those rules across the operating day, then the endpoint and error catalogues.

## 2. Global Specifications & System-Wide Principles

This section defines the rules that apply uniformly across every resource and endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the caller's operational capacity. A request whose `X-User-Role` header is missing or names an undeclared role, or whose `X-User-ID` is missing, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). An empty or whitespace-only `X-User-ID` counts as missing. A request whose role is declared but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403).

Six roles are recognized, spelled exactly as follows:

- `PortAuthorityAdmin` — port authority staff; owns terminal configuration, the berth registry, the vessel registry, weather advisories, the operations checkpoint, and the logical clock. May also open a port call for any vessel.
- `Harbormaster` — the berth and movement authority; owns berth assignment and confirmation, arrival and departure recording, and acceptance of revised schedules. Shares service-order approval and rejection with the terminal floor, and is the sole approver while the terminal is `CONSTRAINED`.
- `TerminalOperator` — the terminal floor; runs passenger flow, baggage, screening lanes, service execution, and the ground-transport queue.
- `VesselAgent` — the shipping-line agent for one vessel; acts only on its own vessel's port calls and their child records.
- `CustomsOfficer` — the customs liaison; owns the per-call customs case and per-passenger customs actions.
- `BillingClerk` — port finance; owns provisional and final invoicing, issuing, settlement, credit adjustments, and call closeout.

Role identity is defined precisely. When `X-User-Role` is `PortAuthorityAdmin`, `Harbormaster`, `TerminalOperator`, `CustomsOfficer`, or `BillingClerk`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `requested_by_user_id` or `approved_by_user_id` on a service order) but never compares it to any entity's `id`. When `X-User-Role` is `VesselAgent`, `X-User-ID` is the `id` of the acting Vessel; ownership checks on any resource that references a Vessel compare the resource's vessel reference to `X-User-ID`. A `VesselAgent` acting on a port call whose `vessel_id` does not equal its `X-User-ID` — directly, or via a referenced child record of such a call — is rejected with `ERR_VESSEL_SCOPE` (HTTP 403). List endpoints filter to the agent's own vessel's calls; single-resource reads and child collections attached to another vessel's call are likewise rejected with `ERR_VESSEL_SCOPE`. On the child-record list endpoints, an explicit filter that resolves to another vessel's port call — `port_call_id` on any child list, or `manifest_entry_id` on the baggage list — is likewise rejected with `ERR_VESSEL_SCOPE` rather than returning an empty page; only the port-calls list itself filters silently.

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

List endpoints paginate through two optional query parameters. The `limit` parameter caps the number of returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. A `limit` that is not an integer, falls below 1, or exceeds 100, and an `offset` that is not an integer or is negative, are rejected with `ERR_VALIDATION` (HTTP 400); unrecognized query parameters are ignored. Every list response orders its items by `created_at` in ascending order — ties on `created_at` are broken by creation sequence, earliest created first — and the `meta` object of every list response carries the four pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. The Logical Clock

All time-dependent behavior in the system — advisory windows, posture derivation, occupancy sweeps, dispatch windows, and turnaround arithmetic — evaluates against a **logical clock**, never against wall-clock time. At startup the logical clock reads exactly 2026-08-01T00:00:00Z, and before any explicit set it continues to read that default; it never silently falls back to the host clock. A `PortAuthorityAdmin` may advance or set the clock through an admin-only, test-driving capability that accepts a target instant in the `to_iso8601` field and answers with the clock's new reading in `current_utc`. Setting the clock re-evaluates posture and every time-gated rule against the new now. Every server-emitted timestamp — `created_at`, `updated_at`, and the `meta.api_request_timestamp` of every response — is likewise rendered from the logical clock, never from the host wall clock.

### 2.5. Terminal Posture and Berth Occupancy

Each terminal's operating posture is a computed, read-time derivation from its berth inventory and its weather picture. Three counters feed it: `active_berth_count` is the number of the terminal's berths currently in `ACTIVE` status; `occupied_berth_count` is the number of distinct berths currently holding a berth assignment in `ACTIVE` status; and `free_berth_count` is the former minus the latter.

From these, the terminal's `posture` takes exactly one of three values. The posture is `EMERGENCY` whenever the terminal has an `ACTIVE` weather advisory of severity `EMERGENCY` whose window covers the logical now. Failing that, the posture is `CONSTRAINED` whenever the terminal has an `ACTIVE` advisory of severity `WARNING` whose window covers the logical now, or when `free_berth_count` is zero — the zero-free-berth condition bites only once the terminal has at least one `ACTIVE` berth, so a terminal with no `ACTIVE` berths at all reads `free_berth_count` as zero without becoming `CONSTRAINED`. Otherwise the posture is `OPERATIONAL`. An advisory covers the logical now when its `window_start` is at or before now and now is strictly before its `window_end` — a half-open window, inclusive at the start and exclusive at the end. Advisories of severity `WATCH` never affect posture, regardless of their window.

Posture and the three counters are recomputed at every read of the terminal, and eagerly whenever the inputs change: when a weather advisory is created, cancelled, or expired; when a berth moves between `ACTIVE` and `OUT_OF_SERVICE` (including berth creation); and when a berth assignment becomes `ACTIVE` or is `RELEASED`.

Posture is not advisory decoration — it gates operations. While the posture is `EMERGENCY`, five operations are refused with `ERR_POSTURE_EMERGENCY` (HTTP 409): creating a berth assignment, confirming a berth assignment, approving a service order, dispatching a ground-transport slot, and departing a port call. While the posture is `CONSTRAINED`, service-order approval is reserved to the `Harbormaster` alone, and every order approved under `CONSTRAINED` carries a surcharge flag that raises its billed rate by ten percent (§3.7, §3.8).

### 2.6. Common Resource Properties

Every resource in this API — Terminal, Berth, Vessel, PortCall, BerthAssignment, ManifestEntry, BaggageItem, ScreeningLane, CustomsCase, ServiceOrder, Invoice, TransportSlot, and WeatherAdvisory — carries four system-managed properties:

- `id` — a server-minted UUID, with no type prefix, assigned at creation.
- `created_at` — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation of the resource.
- `version` — an integer that starts at 1 at creation and increments with every modification of the resource; it is the basis for the optimistic-concurrency rules of §2.8.

All datetime-typed business fields (for example `scheduled_eta`, `window_start`, `actual_etd`) are ISO 8601 UTC timestamps. Recomputed derived values on a resource — a terminal's posture, a call's aboard counts, an invoice's totals — are mutations of that resource and therefore refresh its `updated_at` and, where the owning workflow says so, increment its `version`.

### 2.7. Monetary Precision and Rounding

All monetary values are integer cents; the API never emits fractional cents, and no fee is ever computed in floating point. Rounding is deliberately rare and pinned to named steps. Partial hours in every duration derivation are rounded **up** to the next whole hour before any multiplication (the screening staffing derivation is the one exception: it rounds the turnaround length **down** to whole hours, as stated in §3.5). A "round half up" step, where a workflow names one, rounds a value ending in exactly half a cent upward. The only round-half-up steps in the entire system are: the overtime amount and the late-penalty amount of the final dockage fee, the per-direction-side volume discount of the passenger head tax, and the per-order-line surcharge of the service fee. Invoice gross and total arithmetic adds and subtracts already-rounded integer cents with no additional rounding of its own.

### 2.8. Optimistic Concurrency Control

Exactly two write operations in the API are guarded by optimistic concurrency control, and each names its own version field.

Creating a berth assignment for a port call must carry `expected_port_call_version`, holding the caller's last observed `version` of that port call. Because creating an assignment supersedes the call's live assignment, a create whose `expected_port_call_version` differs from the call's current `version` — whether trailing or ahead — is rejected with `ERR_STALE_VERSION` (HTTP 412): the caller's view of which assignment is live is stale, and its supersede decision is void.

Posting a credit adjustment to an invoice must carry `expected_invoice_version`, holding the caller's last observed `version` of that invoice. A post whose `expected_invoice_version` differs from the invoice's current `version` — whether trailing or ahead — is rejected with `ERR_STALE_INVOICE_VERSION` (HTTP 412): the credit ceiling — the invoice's `total_cents` — that the caller validated against may no longer be current.

No endpoint other than these two accepts a version field.

### 2.9. Request Validation Pipeline

Incoming requests are validated in a fixed priority order, so that when several checks could fail, the rejection is deterministic. Existence checks in particular run left to right: path identifiers are validated in path order, then body foreign-key references, and the first missing reference yields `ERR_NOT_FOUND` (HTTP 404) before any business rule is consulted. The full pipeline order is:

1. Authentication: the `X-User-Role` header is present and names a declared role, and `X-User-ID` is present — otherwise `ERR_UNAUTHENTICATED` (401).
2. Authorization: the role is permitted on this endpoint — otherwise `ERR_FORBIDDEN` (403).
3. Existence: path ids and body foreign-key references exist, validated left-to-right — otherwise `ERR_NOT_FOUND` (404).
4. Vessel scope: a `VesselAgent`'s `X-User-ID` must equal the `vessel_id` of the owning port call, directly or via the referenced child — otherwise `ERR_VESSEL_SCOPE` (403).
5. Optimistic concurrency: `expected_port_call_version` or `expected_invoice_version` must equal the parent's current `version` — otherwise `ERR_STALE_VERSION` or `ERR_STALE_INVOICE_VERSION` (412).
6. Request body shape: required fields present, types and enum values valid, integer ranges respected — otherwise `ERR_VALIDATION` (400). The body must be a JSON object (a non-object or malformed body fails here), and unrecognized body fields are ignored.
7. Direction applicability: check-in, screen, board, and offload require an `EMBARK` entry; disembark, customs-hold, and customs-release require a `DEBARK` entry; loading a bag requires an `EMBARK` entry and delivering a bag requires a `DEBARK` entry — otherwise `ERR_MANIFEST_DIRECTION` (422). Direction is evaluated before state preconditions because the operation is undefined for the other direction's flow.
8. State preconditions: the target entity is in a state from which the requested transition exists, including parent-state gates on child creation — otherwise `ERR_INVALID_STATE` (409).
9. Posture gate: `EMERGENCY` blocks assignment create and confirm, service-order approve, transport dispatch, and port-call depart — otherwise `ERR_POSTURE_EMERGENCY` (409).
10. Berth physical fit — otherwise `ERR_BERTH_NOT_FIT` (422).
11. Contamination sequencing — otherwise `ERR_WASTE_BEFORE_PROVISIONING` (409).
12. Turnaround minimum on call create and delay — otherwise `ERR_TURNAROUND_TOO_SHORT` (422).
13. Window sanity and containment — otherwise `ERR_WINDOW_NOT_CONTAINED`, `ERR_ADVISORY_WINDOW_INVALID`, or `ERR_SERVICE_WINDOW_OUTSIDE_BERTH` (422).
14. Buffered berth overlap — otherwise `ERR_BERTH_WINDOW_CONFLICT` (409).
15. Configuration-label uniqueness: `berth_code`, `lane_code`, and `voyage_ref` within a terminal — otherwise `ERR_VALIDATION` (400).
16. Operational-record uniqueness — otherwise `ERR_DUPLICATE_MANIFEST_REF`, `ERR_DUPLICATE_TAG`, `ERR_DUPLICATE_CUSTOMS_CASE`, or `ERR_INVOICE_KIND_EXISTS` (409).
17. Segregation of duties on service-order approval — otherwise `ERR_SEGREGATION_OF_DUTIES` (409).
18. Conditional role: under `CONSTRAINED` posture only the `Harbormaster` may approve service orders — otherwise `ERR_CONSTRAINED_REQUIRES_HARBORMASTER` (403).
19. Capacity thresholds — otherwise `ERR_SCREENING_CAPACITY`, `ERR_APRON_CAPACITY`, or `ERR_QUEUE_WINDOW_FULL` (409).
20. Queue discipline — otherwise `ERR_QUEUE_ORDER` or `ERR_REQUEUE_LIMIT` (409).
21. Customs coordination — otherwise `ERR_CUSTOMS_NOT_CLEARED` or `ERR_CUSTOMS_HOLD_ACTIVE` (409).
22. Departure completeness — otherwise `ERR_OPEN_MISTAGS` or `ERR_OPEN_SERVICE_ORDERS` (409).
23. Settlement exactness — otherwise `ERR_UNDERPAYMENT` or `ERR_OVERPAYMENT` (422).
24. Credit ceiling on adjustments — otherwise `ERR_CREDIT_EXCEEDS_OUTSTANDING` (422).

### 2.10. Cascades and System-Initiated Transitions

Many state changes in this API are not client-requested at all: they are side effects of a transition on a related entity, or of the passage of the logical clock. Accepting revised arrival times can supersede a berth assignment, reject the service orders that lost their window, and recompute the provisional invoice in a single three-hop cascade; departure releases the berth, marks no-shows, offloads their bags, and refreshes the aboard counts; cancelling a call sweeps every child record into a terminal state; the operations checkpoint expires time-lapsed records. Where a cascade has multiple hops, the hops run in their documented order — each hop's outputs are the next hop's inputs — and every entity mutated along the way has its `updated_at` refreshed and, where the transition specifies it, its `version` incremented. Child mutations that change a parent's derived state — berth occupancy, aboard counts, invoice totals — propagate upward immediately: consistency in this system is immediate, never deferred.

## 3. Business Logic & Workflows

### 3.1. Establishing the Port: Terminals, Berths, and the Vessel Registry

Before any vessel can be scheduled, a `PortAuthorityAdmin` registers the **Terminal** itself: a display `name`, the `max_apron_slots` ceiling on how many service orders may be concurrently `IN_PROGRESS` anywhere on the apron, and the `taxi_dispatch_capacity_per_window` ceiling on ground-transport dispatches per fifteen-minute window. Both capacity knobs must be integers of at least 1. A newly created terminal starts clean: `posture` is `OPERATIONAL`, the occupancy counters `occupied_berth_count`, `active_berth_count`, and `free_berth_count` are all zero, and the checkpoint counter `ops_run_index` starts at 0.

Berths join the terminal through the same administrator, each carrying its owning `terminal_id`, a human-readable `berth_code` that must be unique within that terminal (a duplicate is rejected with `ERR_VALIDATION`), a usable face `length_ft` given as an integer of at least 100 feet, and a `max_draft_ft` greater than zero (any positive number; fractional values are accepted). A berth is born `ACTIVE`. Taking a berth out of service is defined only from `ACTIVE` and is refused while any assignment on that berth is `ACTIVE` — either failure is rejected with `ERR_INVALID_STATE` — but assignments merely `TENTATIVE` on the berth are left in place and are only caught later, at confirmation time. Returning a berth to service carries no assignment-related preconditions but is likewise defined only from `OUT_OF_SERVICE`; any other status is rejected with `ERR_INVALID_STATE`. Berth creation, removal from service, and return to service each recompute the terminal's berth counters and posture per §2.5, and the berth's own `status` (`ACTIVE` or `OUT_OF_SERVICE`) is the only state it carries. Berths may be listed with optional `terminal_id` and `status` filters alongside the standard pagination parameters.

The vessel registry is likewise administered by the `PortAuthorityAdmin`. Each Vessel is registered against its home `terminal_id` with a `name`, an integer length overall `loa_ft` of at least 50 feet, a `draft_ft` greater than zero (any positive number; fractional values are accepted), an integer `pax_capacity` of at least 1, and an integer `crew_count` of zero or more. These physical numbers are not decorative: `loa_ft` and `draft_ft` drive the berth-fit rule of §3.3, and `loa_ft` again drives the tiered dockage rate of §3.8. Vessels may be listed filtered by `terminal_id`.

### 3.2. Scheduling a Port Call: Booking, Delay, and Cancellation

A **PortCall** is the unit of everything else in this system. A `VesselAgent` opens one for its own vessel — the payload's `vessel_id` must equal the caller's `X-User-ID`, or the request is rejected with `ERR_VESSEL_SCOPE` — while a `PortAuthorityAdmin` may open a call for any vessel. The creation payload names the hosting `terminal_id`, the calling `vessel_id`, a `voyage_ref` that must be unique within the terminal (duplicates are rejected with `ERR_VALIDATION`), the scheduled arrival `scheduled_eta` and scheduled departure `scheduled_etd`, and the booked manifests: `booked_embark_pax` and `booked_debark_pax`, each an integer of zero or more. One feasibility rule guards the booking: the span from `scheduled_eta` to `scheduled_etd` must be at least six hours, and a span of exactly six hours is allowed; anything shorter is rejected with `ERR_TURNAROUND_TOO_SHORT` (HTTP 422). A new call is `SCHEDULED`. Its revision fields `revised_eta`, `revised_etd`, and `delay_reason` remain null until the first delay is recorded, and `actual_eta` and `actual_etd` remain null until the call has actually arrived and departed. Two computed counters track the day: `passengers_aboard` counts the call's manifest entries currently in `EMBARKED`, and `bags_aboard` counts the call's baggage items currently in `LOADED`.

When a vessel runs late, its agent records a delay by supplying `revised_eta`, `revised_etd`, and a free-text `reason` — all three fields are required. Delay is only possible from `SCHEDULED`, and the revised pair must satisfy the same six-hour turnaround minimum — measured from `revised_eta` to `revised_etd` — or the delay is rejected with `ERR_TURNAROUND_TOO_SHORT`. A recorded delay moves the call from `SCHEDULED` to `DELAYED`, stores the three values (with the payload's `reason` persisted as `delay_reason`), and increments the call's `version` by 1.

Acceptance of a revised schedule belongs to the `Harbormaster`. Confirming the revision moves the call from `DELAYED` back to `SCHEDULED`, overwrites `scheduled_eta` and `scheduled_etd` with the revised values, and then fires a pinned three-hop cascade. Hop 1: this call's `CONFIRMED` berth assignment whose window no longer contains the new schedule — that is, whose `window_start` falls after the new `scheduled_eta` or whose `window_end` falls before the new `scheduled_etd` — becomes `SUPERSEDED`, releasing its berth window. Hop 2, caused by hop 1: this call's service orders in `REQUESTED` or `APPROVED` whose requested window is not contained in any remaining live (`TENTATIVE`, `CONFIRMED`, or `ACTIVE`) assignment window of the call become `REJECTED`, with `reject_reason` set to `WINDOW_LOST`. Hop 3, caused by hop 2: the call's `PROVISIONAL` invoice, if one exists in `DRAFT`, recomputes `service_fee_cents` — rejected orders now contribute zero — and with it `gross_cents` and `total_cents`. The call's `version` increments by 1. Delay and confirm-revised form a revision loop that may repeat as often as the schedule demands.

Cancellation is the other way out of the schedule, available from either `SCHEDULED` or `DELAYED` to the vessel's own `VesselAgent` or to the `Harbormaster`, with an optional `reason`. Cancelling a call fires the full compensation cascade: any live berth assignment of the call (`TENTATIVE` or `CONFIRMED`) becomes `SUPERSEDED`; service orders in `REQUESTED` or `APPROVED` become `CANCELLED`; the call's `QUEUED` transport slots become `EXPIRED`; a `DRAFT` or `ISSUED` `PROVISIONAL` invoice becomes `CANCELLED` (a `FINAL` invoice can never exist yet, because final billing only begins at close, long after cancellation is possible); every manifest entry not yet in a terminal state becomes `CANCELLED`; and every non-terminal baggage item of the call becomes `CANCELLED`. The call's `version` increments by 1, and the call lands in `CANCELLED`. The call's terminal states are `CLOSED` and `CANCELLED`.

Port calls are readable by every role, with optional `terminal_id`, `vessel_id`, and `status` filters on the list; for a `VesselAgent`, the list contains only its own vessel's calls, and reads or child collections attached to another vessel's call are rejected with `ERR_VESSEL_SCOPE`.

### 3.3. Berth Assignment and the Turnaround Window

Pinning a call to a berth is the `Harbormaster`'s office. The creation request names the `berth_id` and the occupation window — `window_start` and `window_end`, a half-open interval that occupies the berth from `window_start` inclusive to `window_end` exclusive — and it must carry `expected_port_call_version` per the optimistic-concurrency rule of §2.8, rejected with `ERR_STALE_VERSION` when the caller's view of the call is stale. Creating an assignment for a call supersedes the call's existing live assignment: any `TENTATIVE` or `CONFIRMED` assignment of that call becomes `SUPERSEDED` and its berth window is released. When the superseded assignment was `CONFIRMED`, the same window-loss chain described for confirm-revised fires — the call's `REQUESTED` or `APPROVED` service orders whose window is no longer contained in a remaining live assignment window become `REJECTED` with `reject_reason` `WINDOW_LOST`, and a `DRAFT` `PROVISIONAL` invoice, if present, recomputes `service_fee_cents`, `gross_cents`, and `total_cents`. The newly created `TENTATIVE` assignment counts among the remaining live windows when that chain evaluates containment. Berth assignments may be listed with `port_call_id`, `berth_id`, and `status` filters.

Three checks guard the creation itself, and all three are re-checked at confirmation. No port-call status gate applies to creation: the call's own status is never consulted. The terminal's posture must not be `EMERGENCY` (`ERR_POSTURE_EMERGENCY`). The berth must physically fit the vessel: its `length_ft` must be at least the vessel's `loa_ft` plus a 30-foot safety margin — equality is allowed — and its `max_draft_ft` must be at least the vessel's `draft_ft`, again with equality allowed; a short apron face or a shallow berth is rejected with `ERR_BERTH_NOT_FIT` (HTTP 422). And the window must contain the call's schedule: `window_start` no later than `scheduled_eta` and `window_end` no earlier than `scheduled_etd`, otherwise `ERR_WINDOW_NOT_CONTAINED` (HTTP 422). A created assignment starts as `TENTATIVE`, and the port call's `version` increments by 1 on creation.

Confirmation re-validates the assignment against the live world in the pipeline order of §2.9: the assignment must still be `TENTATIVE` and the berth must be `ACTIVE` (a berth taken out of service since creation fails here with `ERR_INVALID_STATE`); the posture must not be `EMERGENCY`; fit and containment are re-checked; and finally the buffered-overlap rule runs. Against every other assignment on the same berth in `CONFIRMED` or `ACTIVE`, the candidate conflicts unless its window ends at least 120 minutes before the other window starts, or its window starts no earlier than 120 minutes after the other window ends — a mandatory buffer of two full hours on both sides, with a gap of exactly 120 minutes on either side allowed. Assignments in `TENTATIVE`, `SUPERSEDED`, `EXPIRED`, or `RELEASED` never block anyone. A violation is rejected with `ERR_BERTH_WINDOW_CONFLICT` (HTTP 409). Confirmation itself has no side effects beyond the state change to `CONFIRMED`.

Arrival belongs to the `Harbormaster` and is accepted only from `SCHEDULED` — a `DELAYED` call must first be confirm-revised back to `SCHEDULED`. The arrival payload carries `actual_eta`. The call must hold a `CONFIRMED` assignment, or the arrival is rejected with `ERR_INVALID_STATE`, and `actual_eta` must fall within that assignment's window — no earlier than its `window_start` and no later than its `window_end`, inclusive at both ends — or the rejection is `ERR_WINDOW_NOT_CONTAINED`. A recorded arrival stamps `actual_eta`, flips that assignment from `CONFIRMED` to `ACTIVE`, recomputes the terminal's occupancy counters and posture, moves the call `SCHEDULED` → `ARRIVED`, and increments the call's `version` by 1.

With the vessel alongside, a `TerminalOperator` begins the turnaround. The gate is screening staffing, computed per §3.5: the officers assigned across the terminal's `OPEN` screening lanes must meet the staffing requirement derived from the call's booked embarking passengers, or the request is rejected with `ERR_SCREENING_CAPACITY` (HTTP 409). Beginning the turnaround moves the call `ARRIVED` → `TURNAROUND` and increments its `version` by 1.

Departure, again the `Harbormaster`'s call, is the most heavily gated transition in the system. From `TURNAROUND`, four conditions must hold, evaluated in pipeline order: the terminal's posture must not be `EMERGENCY` (`ERR_POSTURE_EMERGENCY`); the call's customs case must be `CLEARED` (`ERR_CUSTOMS_NOT_CLEARED`); no baggage item of the call may remain in `MISTAGGED` or `RECOVERED` (`ERR_OPEN_MISTAGS`); and every service order of the call must be in `COMPLETED`, `REJECTED`, or `CANCELLED` (`ERR_OPEN_SERVICE_ORDERS`). The payload's `actual_etd` is stamped on the call. Departure releases the berth — the `ACTIVE` assignment becomes `RELEASED` and the terminal's occupancy and posture are recomputed — and then cascades through the manifests: the call's `EMBARK` entries still in `BOOKED`, `CHECKED_IN`, or `SCREENED` become `NO_SHOW`, and its `DEBARK` entries still `ABOARD` become `CARRIED_AWAY`. Each newly `NO_SHOW` entry's bags in `CHECKED` or `STAGED` become `OFFLOADED`, and any bag of such an entry still `LOADED` is likewise offloaded, decrementing `bags_aboard` per bag. Finally `passengers_aboard` and `bags_aboard` are recomputed, the call moves `TURNAROUND` → `DEPARTED`, and its `version` increments by 1.

Closing the books is the `BillingClerk`'s act: from `DEPARTED` to `CLOSED`, which generates the call's `FINAL` invoice in `DRAFT` with all figures computed from actuals per §3.8, and increments the call's `version` by 1. The response answers 200 with the updated port call in `data`; the generated `FINAL` invoice is read back through the invoice endpoints.

### 3.4. Weather Advisories and the Operations Checkpoint

Weather enters the system as a **WeatherAdvisory**, posted by a `PortAuthorityAdmin` with the affected `terminal_id`, a `severity` of `WATCH`, `WARNING`, or `EMERGENCY`, and a window: `window_start` inclusive, `window_end` exclusive. The window must be sane — `window_end` strictly later than `window_start` — or the advisory is rejected with `ERR_ADVISORY_WINDOW_INVALID` (HTTP 422). An advisory is born `ACTIVE`, and its creation recomputes the terminal's posture immediately per §2.5: a live `EMERGENCY` advisory forces the `EMERGENCY` posture, a live `WARNING` advisory forces at least `CONSTRAINED`, and a `WATCH` never gates anything. Cancelling an advisory moves it `ACTIVE` → `CANCELLED` and recomputes posture again. Advisories may be listed with `terminal_id`, `status`, and `severity` filters.

Time itself moves advisories to their grave. The **operations checkpoint** — an admin-only capability restricted to `PortAuthorityAdmin` — sweeps the terminal against the logical clock: every `ACTIVE` advisory whose `window_end` is at or before the logical now becomes `EXPIRED`; every `TENTATIVE` berth assignment whose `window_start` is at or before the logical now becomes `EXPIRED`, its hold on the berth lapsed; and every `QUEUED` transport slot whose port call has reached `DEPARTED`, `CLOSED`, or `CANCELLED` becomes `EXPIRED`. The sweep then recomputes the terminal's posture, increments `ops_run_index` by 1 — a monotone counter of how many checkpoints the terminal has run — and increments the terminal's `version` by 1.

Posture's consequences, stated in §2.5, converge here in operational terms. Under `EMERGENCY`, assignment creation and confirmation, service-order approval, transport dispatch, and departure are all refused with `ERR_POSTURE_EMERGENCY`. Under `CONSTRAINED`, service-order approval narrows to the `Harbormaster` alone, and any order approved in that posture carries the ten-percent surcharge flag into billing. And because posture derives partly from `free_berth_count`, every arrival that occupies the last free berth quietly tightens the terminal's operating rules without any human announcement.

### 3.5. Passenger Flow: Manifests, Screening, and Customs

Every human being who moves through the terminal appears as a **ManifestEntry**, added by the `VesselAgent` of the calling vessel while the call is `SCHEDULED` or `DELAYED` — a parent-state gate on child creation, enforced with `ERR_INVALID_STATE` once the call has moved on. Each entry carries a `passenger_ref` that must be unique within its port call (duplicates are rejected with `ERR_DUPLICATE_MANIFEST_REF`), a `direction`, and a `cabin_class` of `STANDARD`, `PREMIUM`, or `CREW`. The `direction` selects the entire flow: an `EMBARK` entry begins in `BOOKED`; a `DEBARK` entry begins `ABOARD`. A derived flag, `is_taxable`, is true for every entry whose `cabin_class` is not `CREW`; `CREW` entries are exempt from the passenger head tax of §3.8. The terminal states of a manifest entry are `EMBARKED`, `NO_SHOW`, `CLEARED`, `CARRIED_AWAY`, and `CANCELLED`. Entries may be listed with `port_call_id`, `status`, and `direction` filters.

Security screening runs through **ScreeningLane** resources, created by a `PortAuthorityAdmin` against a `terminal_id` with a `lane_code` that must be unique within that terminal (a duplicate is rejected with `ERR_VALIDATION`). A lane is created `CLOSED` with `officers_assigned` at 0. A `TerminalOperator` opens a lane by supplying `officers_assigned`, which must be an integer of at least 1 — a lane cannot open unstaffed, and the attempt is rejected with `ERR_VALIDATION`; opening records the supplied staffing on the lane. Opening is defined only from `CLOSED`, and closing only from `OPEN` — any other status is rejected with `ERR_INVALID_STATE`. Closing a lane returns it to `CLOSED` and resets `officers_assigned` to 0. Only `OPEN` lanes count toward staffing. Lanes may be listed with `terminal_id` and `status` filters.

How much staffing is enough is a computed answer, not a judgement call, and it is available as a computed read for any port call to the `PortAuthorityAdmin`, `Harbormaster`, and `TerminalOperator` roles. The read takes the target call as a required `port_call_id` query parameter — missing, the request fails with `ERR_VALIDATION` — and an optional `mode` query parameter that defaults to `PROJECTION` and rejects any other value but `PROJECTION` or `ACTUAL` with `ERR_VALIDATION`; the call is not checked against the path terminal. Two time quantities frame the requirement. The turnaround length in whole hours is the scheduled span from `scheduled_eta` to `scheduled_etd`, measured in seconds, divided by 3,600, and rounded down. The embarkation window, reported as `embark_window_hours`, is that turnaround length minus two tail hours reserved at the end of the call, raised to a floor of one hour and capped at eight hours. The officer requirement, `required_officers`, divides the passenger numerator by the per-window officer throughput — sixty passengers per officer per hour, multiplied by the embarkation window in hours — and rounds the quotient up to a whole officer. The numerator depends on the requested `mode`: under the default `PROJECTION` mode it is the call's `booked_embark_pax`; under `ACTUAL` mode it is the count of the call's `EMBARK` entries currently in `CHECKED_IN`, `SCREENED`, or `EMBARKED`, so the requirement tightens or relaxes as check-ins actually arrive. The read also reports `assigned_officers` — the sum of `officers_assigned` across the terminal's `OPEN` lanes only — and `satisfied`, which is true exactly when `assigned_officers` is at least `required_officers`; equality satisfies. Beginning a turnaround (§3.3) evaluates this same requirement in its `PROJECTION` variant.

The embarkation chain is walked by the `TerminalOperator`, one passenger at a time, and every step checks the entry's `direction` first — an action invoked on an entry of the wrong direction is rejected with `ERR_MANIFEST_DIRECTION` before any state check runs. **Check-in** moves an `EMBARK` entry from `BOOKED` to `CHECKED_IN` while the call is `SCHEDULED`, `ARRIVED`, or `TURNAROUND`. **Screening** moves it from `CHECKED_IN` to `SCREENED`, requires the call to be `ARRIVED` or `TURNAROUND`, and additionally requires at least one `OPEN` screening lane of the terminal with at least one officer assigned — otherwise `ERR_SCREENING_CAPACITY`. **Boarding** moves it from `SCREENED` to `EMBARKED`, requires the call to be `TURNAROUND`, and requires the call's customs case to be `CLEARED` — otherwise `ERR_CUSTOMS_NOT_CLEARED`; each boarding adds one to the call's `passengers_aboard`. Boarding has a compensating action: **offloading** an `EMBARKED` entry returns it to `CHECKED_IN`, is only possible while the call is `TURNAROUND`, subtracts one from `passengers_aboard`, and cascades — every bag of the entry currently `LOADED` becomes `OFFLOADED`, with `bags_aboard` decremented once per offloaded bag. The aboard counts are conserved across the board/offload pair.

The debarkation chain begins when a `TerminalOperator` **disembarks** a `DEBARK` entry, moving it from `ABOARD` to `DISEMBARKED`. The call must be `ARRIVED` or `TURNAROUND`, and the call's customs case must be `FILED` or `CLEARED`: while the case is `HELD` the disembark is rejected with `ERR_CUSTOMS_HOLD_ACTIVE`, and a case that has not yet reached `FILED` fails the same gate with `ERR_CUSTOMS_NOT_CLEARED`. From `DISEMBARKED`, a `CustomsOfficer` may place the individual on `customs-hold`, moving the entry to `HELD`, or grant `customs-release`, moving it to `CLEARED`; a `HELD` entry is likewise released to `CLEARED` by the same action. These two actions require a `DEBARK` entry and are rejected with `ERR_MANIFEST_DIRECTION` otherwise.

The **CustomsCase** itself is the per-call dossier owned by the `CustomsOfficer`. There is at most one case per port call — a second attempt is rejected with `ERR_DUPLICATE_CUSTOMS_CASE` — and it may be created while the call is `SCHEDULED`, `DELAYED`, `ARRIVED`, or `TURNAROUND`. A case begins in `DRAFT`. **Filing** moves it from `DRAFT` to `FILED`, a transition gated on the call still being in one of those four pre-departure states (`ERR_INVALID_STATE` past them). **Holding** moves a `FILED` case to `HELD`, records the payload's required `reason` as `hold_reason`, and cascades: every `DEBARK` manifest entry of the call currently `DISEMBARKED` becomes `HELD`. A `HELD` case can be re-filed back to `FILED` with no preconditions, and this revision loop — `FILED` → `HELD` → `FILED` — re-allows disembarkation each time around. **Clearing** moves a `FILED` case to its terminal state `CLEARED`. Clearing the case does not release entries already `HELD`; each held passenger needs an individual `customs-release`. Customs cases may be listed with `port_call_id` and `status` filters.

### 3.6. Baggage Handling and Mistag Recovery

Bags are checked by a `TerminalOperator` against the passenger movement that owns them: the payload names the `manifest_entry_id` and a `tag_code` that must be unique within the port call, with duplicates rejected as `ERR_DUPLICATE_TAG`. The owning entry must not be `NO_SHOW`, `CANCELLED`, or `CARRIED_AWAY`. Each bag's `port_call_id` is denormalized from its manifest entry at creation — the system copies it, the client does not supply it — so that terminal-wide baggage sweeps can find every bag of a call directly. A new bag starts in `CHECKED`. Bags may be listed with `manifest_entry_id`, `port_call_id`, `status`, and `tag_code` filters.

The normal flows split by direction at the apron. **Staging** a bag moves it to `STAGED`: from `CHECKED` this requires the owning entry to be in `CHECKED_IN`, `SCREENED`, `EMBARKED`, `DISEMBARKED`, or `CLEARED` — otherwise `ERR_INVALID_STATE`. **Loading** moves a `STAGED` bag to `LOADED` and is an embark-side act: the owning entry's `direction` must be `EMBARK` (`ERR_MANIFEST_DIRECTION` otherwise), the entry itself must be `EMBARKED` (`ERR_INVALID_STATE`), and the call must be `TURNAROUND`; each load adds one to the call's `bags_aboard`. **Delivery** is the debark-side mirror: a `STAGED` bag becomes `DELIVERED` only when its owning entry's `direction` is `DEBARK` (`ERR_MANIFEST_DIRECTION` otherwise) and the entry has been `CLEARED` by customs — delivering before clearance is rejected with `ERR_CUSTOMS_NOT_CLEARED`.

Mis-tagged baggage has its own loop. A `TerminalOperator` may report a mistag on any bag in `CHECKED` or `STAGED`, optionally attaching a free-text `note` (accepted but not persisted on the bag); the bag becomes `MISTAGGED`. Recovering the bag moves it to `RECOVERED`, and re-staging from `RECOVERED` carries no preconditions — the recovery loop `MISTAGGED` → `RECOVERED` → `STAGED` re-enters the normal flow at the staging step. Mistags are not merely operational noise: departure is blocked while any bag of the call remains in `MISTAGGED` or `RECOVERED` (§3.3). Bags also move without being touched: an entry-level offload offloads the entry's `LOADED` bags; departure offloads the `CHECKED` and `STAGED` bags of every newly `NO_SHOW` entry along with any of their bags still `LOADED`; and cancelling the call cancels every non-terminal bag. The terminal baggage states are `DELIVERED`, `OFFLOADED`, and `CANCELLED`.

### 3.7. Apron Services: Provisioning and Waste Offload

Provisioning pallets and waste offload are both modeled as a **ServiceOrder**, requested by the calling vessel's `VesselAgent` while the call is `SCHEDULED`, `DELAYED`, `ARRIVED`, or `TURNAROUND`. The request names the `kind` — `PROVISIONING` or `WASTE_OFFLOAD` — the planned `units` (pallets or tons, an integer of at least 1), and the requested service window `window_start` to `window_end`. The caller's `X-User-ID` is recorded as `requested_by_user_id`, anchoring the segregation-of-duties rule below, and the order begins in `REQUESTED`. The window's legitimacy is not judged at request time; it is judged at approval time.

Approval is shared between the `TerminalOperator` and the `Harbormaster`, but posture and duty rules narrow it. The checks fire in pipeline order. First, the posture gate: under `EMERGENCY` no approval is possible — `ERR_POSTURE_EMERGENCY`. Second, window containment: the order's requested window must be contained in a live (`TENTATIVE`, `CONFIRMED`, or `ACTIVE`) berth-assignment window of the call, otherwise `ERR_SERVICE_WINDOW_OUTSIDE_BERTH` (HTTP 422). Third, segregation of duties: the approver's `X-User-ID` must differ from the order's `requested_by_user_id` — a requester may never approve its own order, and the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 409). Fourth, the conditional role: under `CONSTRAINED` posture only a `Harbormaster` may approve, and a `TerminalOperator`'s attempt is rejected with `ERR_CONSTRAINED_REQUIRES_HARBORMASTER` (HTTP 403); under `OPERATIONAL` either role may approve. An approval records the approver's `X-User-ID` as `approved_by_user_id` (null until this moment), sets `surcharge_applied` to true exactly when the terminal posture at approval is `CONSTRAINED` — the flag that carries the ten-percent surcharge into §3.8, and which defaults to false — and recomputes the call's `DRAFT` `PROVISIONAL` invoice, if one exists, across `service_fee_cents`, `gross_cents`, and `total_cents`.

Rejection and cancellation are the two ways an order dies before execution. Either approving role may reject a `REQUESTED` order, recording the payload's optional `reason` as `reject_reason`. The requesting `VesselAgent` may cancel its own order from `REQUESTED` or `APPROVED`; cancelling an `APPROVED` order recomputes the `DRAFT` `PROVISIONAL` invoice, while a `REQUESTED` order never contributed to any fee and leaves the invoice untouched. And orders can die without any actor at all: the confirm-revised and supersede cascades of §3.2 and §3.3 reject `REQUESTED` and `APPROVED` orders whose windows are lost, stamping `reject_reason` with `WINDOW_LOST` and recomputing the provisional invoice.

Execution belongs to the `TerminalOperator`. **Starting** an `APPROVED` order moves it to `IN_PROGRESS` and is guarded by three checks: an `ACTIVE` berth assignment must exist for the call (`ERR_INVALID_STATE`); the apron must have room, where the rule is aggregate concurrency with no pairwise interval arithmetic — every `IN_PROGRESS` order anywhere on the terminal, across all port calls, consumes one slot regardless of its window times, and a start is rejected with `ERR_APRON_CAPACITY` whenever the terminal's current `IN_PROGRESS` count already equals or exceeds `max_apron_slots` — a count exactly one below the limit passes; and the contamination rule forbids starting a `PROVISIONING` order while a `WASTE_OFFLOAD` of the same call is `IN_PROGRESS` — rejected with `ERR_WASTE_BEFORE_PROVISIONING` — though the reverse sequencing, starting waste offload while provisioning runs, is not restricted. **Completing** an `IN_PROGRESS` order records the payload's required `actual_units` — an integer of zero or more — moves the order to `COMPLETED`, and recomputes the `DRAFT` `PROVISIONAL` invoice. The terminal states of a service order are `COMPLETED`, `REJECTED`, and `CANCELLED`, and orders may be listed with `port_call_id`, `status`, and `kind` filters.

### 3.8. Billing: Dockage, Head Tax, Service Fees, and Settlement

Billing is two-layered by design. A **PROVISIONAL invoice** tracks the call as it evolves; a **FINAL invoice** is struck from actuals when the call closes. Each call carries at most one invoice of each `kind` — a duplicate attempt is rejected with `ERR_INVOICE_KIND_EXISTS`. The `BillingClerk` generates the `PROVISIONAL` invoice once the call holds a `CONFIRMED` or `ACTIVE` berth assignment (without one, the request fails the state gate with `ERR_INVALID_STATE`); the call must not be `CANCELLED` or `CLOSED`. Generation computes all three provisional fee variants plus `gross_cents` and `total_cents`, opens the invoice in `DRAFT`, starts `adjustments_total_cents` at 0, and leaves `payment_cents` and `dispute_reason` null.

The **dockage fee** prices berth time by vessel size. A single, non-marginal tier rate — in cents per length-foot per billed hour — is selected by the vessel's `loa_ft`: 95 cents when length overall is at most 700 feet; 125 cents when it exceeds 700 feet but is at most 1,000 feet; 150 cents when it exceeds 1,000 feet. The scheduled duration in hours, used by both variants, is the span from `scheduled_eta` to `scheduled_etd` measured in seconds, divided by 3,600, and rounded up to a whole hour. The PROVISIONAL variant is deliberately simple: the billed hours are the greater of the scheduled hours and a ten-hour minimum, and `dockage_fee_cents` is `loa_ft` multiplied by the tier rate multiplied by those billed hours — no overtime, no late penalty. The FINAL variant, computed at close from the system-stamped `actual_eta` and `actual_etd` of the departed call, proceeds in five pinned steps. First, the actual duration in hours is the span from `actual_eta` to `actual_etd` in seconds, divided by 3,600, rounded up. Second, the billed base is the greater of the actual hours and the same ten-hour minimum, and the overtime hours are the excess of that billed base over the scheduled hours, or zero when there is no excess. Third, the base amount is `loa_ft` times the tier rate times the non-overtime portion of the billed base; the overtime amount is `loa_ft` times the tier rate times the overtime hours times one and a half, rounded half-up to whole cents; and the subtotal is the sum of the two. Fourth, when `actual_etd` falls later than `scheduled_etd`, a late penalty of ten percent of the subtotal — rounded half-up to whole cents — is assessed; a departure at or before the scheduled time pays none. Fifth, `dockage_fee_cents` is the subtotal plus the late penalty.

The **passenger head tax** is levied per taxable passenger at 1,350 cents, with a volume tier. Which passengers count depends on the variant. The PROVISIONAL variant trusts the booking: the taxable embark side is `booked_embark_pax` and the taxable debark side is `booked_debark_pax`, with no manifest inspection. The FINAL variant counts real manifest rows instead: the embark side is the count of the call's `EMBARK` entries in `EMBARKED` whose `cabin_class` is not `CREW`, and the debark side is the count of `DEBARK` entries in `DISEMBARKED`, `HELD`, or `CLEARED` whose `cabin_class` is not `CREW`. Entries in `BOOKED`, `CHECKED_IN`, `SCREENED`, `NO_SHOW`, or `CANCELLED` never count, nor do `ABOARD` or `CARRIED_AWAY` entries, and `CREW` never counts on either side. When the two sides combined reach at least 3,000 taxable passengers, a five-percent volume discount applies — computed per direction side and pinned in that order: each side's discount is that side's taxable count times 1,350 cents times five percent, rounded half-up to whole cents per side, and `head_tax_cents` is then the embark side's gross minus the embark discount plus the debark side's gross minus the debark discount. Summing the two sides first and rounding once is not conformant; identical booked data can yield a different final tax once actuals diverge. Below the 3,000-passenger tier, `head_tax_cents` is simply the combined taxable count times 1,350 cents.

The **service fee** aggregates the call's service orders at 4,800 cents per unit for `PROVISIONING` and 6,200 cents per unit for `WASTE_OFFLOAD`. Each contributing order produces a line amount — its kind's rate multiplied by its units — and when the order's `surcharge_applied` flag is set, that line amount is increased by ten percent, rounded half-up to whole cents, before any summation; `service_fee_cents` is the sum of the line amounts, surcharge rounding applied per order line and only then summed. The PROVISIONAL variant counts orders in `APPROVED`, `IN_PROGRESS`, or `COMPLETED` at their planned `units`; the FINAL variant counts only `COMPLETED` orders at their `actual_units`; orders in `REQUESTED`, `REJECTED`, or `CANCELLED` contribute zero. Because the provisional layer is live, this fee recomputes — along with `gross_cents` and `total_cents` — whenever an order is approved, completed, cancelled from `APPROVED`, or cascade-rejected, so long as a `DRAFT` `PROVISIONAL` invoice exists.

Invoice arithmetic across the three fees follows a pinned evaluation order that never feeds back on itself: first `dockage_fee_cents` (including its overtime and late penalty), second `head_tax_cents`, third `service_fee_cents`; fourth, `gross_cents` is the sum of those three; fifth, `total_cents` is `gross_cents` minus `adjustments_total_cents`. Posted adjustments never re-enter the three fee steps — they only ever reduce the total.

The invoice lifecycle after generation is short and exact. **Issuing** moves a `DRAFT` invoice to `ISSUED` and increments its `version` by 1. **Settlement** moves an `ISSUED` invoice to `SETTLED` and accepts the payload's `payment_cents` only when it equals `total_cents` exactly: a lesser payment is rejected with `ERR_UNDERPAYMENT` (HTTP 422) and a greater one with `ERR_OVERPAYMENT` (HTTP 422); a successful settle records `payment_cents` and increments the `version`. The billed vessel's `VesselAgent` may instead **dispute** an `ISSUED` invoice, moving it to `DISPUTED` with the payload's required `reason` recorded as `dispute_reason` and incrementing the `version`. A `BillingClerk` resolves disputes — or simply grants credits — by posting an adjustment against an `ISSUED` or `DISPUTED` invoice with an `amount_cents` (a positive integer, at least 1), a `reason` (required), and the `expected_invoice_version` required by §2.8; a stale version is rejected with `ERR_STALE_INVOICE_VERSION`, and an `amount_cents` greater than the invoice's current `total_cents` is rejected with `ERR_CREDIT_EXCEEDS_OUTSTANDING` (HTTP 422). A posted adjustment adds its `amount_cents` into `adjustments_total_cents`, recomputes `total_cents`, returns a `DISPUTED` invoice to `ISSUED` at the adjusted total, and increments the invoice's `version` by 1. Cancelling the port call cancels any `DRAFT` or `ISSUED` `PROVISIONAL` invoice with it; the `FINAL` invoice only exists after close, which cancellation always precedes. The terminal invoice states are `SETTLED` and `CANCELLED`, and invoices may be listed with `port_call_id`, `kind`, and `status` filters.

### 3.9. Ground Transport Dispatch

Debarkation waves end at the curb, and the curb is managed as a queue of **TransportSlot** records. A `TerminalOperator` enqueues a slot with its `terminal_id`, the `port_call_id` of the debark wave being served, a `vehicle_class` of `TAXI`, `SHUTTLE`, or `PRIVATE`, and a `party_size` given as an integer of at least 1, while the call is `SCHEDULED`, `DELAYED`, `ARRIVED`, or `TURNAROUND`; the two references are recorded as supplied, with no check that the call belongs to the named terminal. Each new slot is stamped with the next `queue_seq` — a monotone sequence maintained per terminal and vehicle class, starting at 1 for the class's first slot and incrementing by 1 with each enqueue or requeue, that fixes the first-in-first-out order — starts with `requeue_count` at 0, carries a null `dispatch_window_start` until it is dispatched, and begins life `QUEUED`. Slots may be listed with `terminal_id`, `port_call_id`, `status`, and `vehicle_class` filters.

Dispatch is where the queue disciplines itself. A `TerminalOperator` dispatches the head of a class queue, moving the slot `QUEUED` → `DISPATCHED`, under four conditions, evaluated in the pipeline order of §2.9 — so a window-capacity failure (priority 19) is reported before a queue-order failure (priority 20): the terminal's posture must not be `EMERGENCY` (`ERR_POSTURE_EMERGENCY`); the slot's port call must be `ARRIVED` or `TURNAROUND` (`ERR_INVALID_STATE`); the current dispatch window must have capacity; and strict FIFO — no other `QUEUED` slot of the same terminal and `vehicle_class` may hold a lower `queue_seq`, or the dispatch is rejected with `ERR_QUEUE_ORDER`. The dispatch clock divides time into fifteen-minute windows aligned to quarter-hour boundaries, the current window being the one containing the logical now. A dispatch consumes one unit of its window's `taxi_dispatch_capacity_per_window` and keeps consuming it even after the slot completes or no-shows: the count that matters is the terminal's slots whose `dispatch_window_start` equals the current window's start and whose status is `DISPATCHED`, `COMPLETED`, or `NO_SHOW`. When that count already equals the capacity, the next dispatch in the window is rejected with `ERR_QUEUE_WINDOW_FULL`; `QUEUED` and `EXPIRED` slots consume nothing. A successful dispatch stamps `dispatch_window_start` with the start of the current window.

After dispatch, a slot is either **completed** — `DISPATCHED` → `COMPLETED` — or marked **no-show** — `DISPATCHED` → `NO_SHOW`. A no-show party gets exactly one second chance: requeueing moves the slot `NO_SHOW` → `QUEUED`, increments `requeue_count` by 1, and assigns a fresh `queue_seq`, rejoining at the back of its class queue; the earlier `dispatch_window_start` is left in place and is overwritten only when the slot is next dispatched. A slot whose `requeue_count` has already reached 1 cannot be requeued again — the attempt is rejected with `ERR_REQUEUE_LIMIT`. Slots also expire without ever being dispatched: the operations checkpoint of §3.4 expires every `QUEUED` slot whose port call has reached `DEPARTED`, `CLOSED`, or `CANCELLED`, and cancelling a call expires its `QUEUED` slots immediately. The terminal states of a transport slot are `COMPLETED` and `EXPIRED`.

## 4. Endpoint Definitions

Operations that create a new resource — terminals, berths, vessels, port calls, berth assignments, manifest entries, baggage items, screening lanes, customs cases, service orders, the provisional invoice, credit adjustments, transport slots, and weather advisories — return `201 Created`. Operations that modify an existing resource or answer a query return `200 OK`; this includes the logical-clock set, the operations checkpoint, the computed screening-requirement read, and every state-transition action. Request payloads, response shapes, and side effects are defined by the workflow narratives of §3; this table is a routing summary only.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/port-ops/_clock/set_current_utc` | Set the logical clock | PortAuthorityAdmin |
| POST | `/port-ops/terminals` | Create a terminal | PortAuthorityAdmin |
| GET | `/port-ops/terminals` | List terminals | Any authenticated role |
| GET | `/port-ops/terminals/{id}` | Get a terminal, including computed posture and counts | Any authenticated role |
| POST | `/port-ops/terminals/{id}/run-ops` | Run the operations checkpoint sweep | PortAuthorityAdmin |
| GET | `/port-ops/terminals/{id}/screening-requirement` | Computed screening staffing requirement for a port call | PortAuthorityAdmin, Harbormaster, TerminalOperator |
| POST | `/port-ops/berths` | Create a berth (`ACTIVE`) | PortAuthorityAdmin |
| GET | `/port-ops/berths` | List berths | Any authenticated role |
| GET | `/port-ops/berths/{id}` | Get a berth | Any authenticated role |
| POST | `/port-ops/berths/{id}/out-of-service` | Take a berth out of service | PortAuthorityAdmin |
| POST | `/port-ops/berths/{id}/return-to-service` | Return a berth to service | PortAuthorityAdmin |
| POST | `/port-ops/vessels` | Register a vessel | PortAuthorityAdmin |
| GET | `/port-ops/vessels` | List vessels | Any authenticated role |
| GET | `/port-ops/vessels/{id}` | Get a vessel | Any authenticated role |
| POST | `/port-ops/port-calls` | Create a port call (`SCHEDULED`) | VesselAgent, PortAuthorityAdmin |
| GET | `/port-ops/port-calls` | List port calls (VesselAgent sees only its own vessel's) | Any authenticated role |
| GET | `/port-ops/port-calls/{id}` | Get a port call (VesselAgent scope-enforced) | Any authenticated role |
| POST | `/port-ops/port-calls/{id}/delay` | Record revised times (`SCHEDULED` → `DELAYED`) | VesselAgent |
| POST | `/port-ops/port-calls/{id}/confirm-revised` | Apply revised times (`DELAYED` → `SCHEDULED`) with the loss cascade | Harbormaster |
| POST | `/port-ops/port-calls/{id}/arrive` | Record arrival (`SCHEDULED` → `ARRIVED`) | Harbormaster |
| POST | `/port-ops/port-calls/{id}/begin-turnaround` | Begin the turnaround (`ARRIVED` → `TURNAROUND`) | TerminalOperator |
| POST | `/port-ops/port-calls/{id}/depart` | Record departure (`TURNAROUND` → `DEPARTED`) with cascade | Harbormaster |
| POST | `/port-ops/port-calls/{id}/close` | Close the call (`DEPARTED` → `CLOSED`) and generate the `FINAL` invoice | BillingClerk |
| POST | `/port-ops/port-calls/{id}/cancel` | Cancel the call with the full compensation cascade | VesselAgent, Harbormaster |
| POST | `/port-ops/port-calls/{id}/berth-assignments` | Create a `TENTATIVE` berth assignment (OCC-guarded; supersedes the live assignment) | Harbormaster |
| GET | `/port-ops/berth-assignments` | List berth assignments | Any authenticated role |
| GET | `/port-ops/berth-assignments/{id}` | Get a berth assignment | Any authenticated role |
| POST | `/port-ops/berth-assignments/{id}/confirm` | Confirm a `TENTATIVE` assignment | Harbormaster |
| POST | `/port-ops/port-calls/{id}/manifest-entries` | Add a passenger movement to the call | VesselAgent |
| GET | `/port-ops/manifest-entries` | List manifest entries | Any authenticated role |
| GET | `/port-ops/manifest-entries/{id}` | Get a manifest entry | Any authenticated role |
| POST | `/port-ops/manifest-entries/{id}/check-in` | Check in an `EMBARK` entry (`BOOKED` → `CHECKED_IN`) | TerminalOperator |
| POST | `/port-ops/manifest-entries/{id}/screen` | Screen a checked-in entry (`CHECKED_IN` → `SCREENED`) | TerminalOperator |
| POST | `/port-ops/manifest-entries/{id}/board` | Board a screened entry (`SCREENED` → `EMBARKED`) | TerminalOperator |
| POST | `/port-ops/manifest-entries/{id}/offload` | Offload a boarded entry (`EMBARKED` → `CHECKED_IN`) | TerminalOperator |
| POST | `/port-ops/manifest-entries/{id}/disembark` | Disembark a `DEBARK` entry (`ABOARD` → `DISEMBARKED`) | TerminalOperator |
| POST | `/port-ops/manifest-entries/{id}/customs-hold` | Hold a disembarked entry (`DISEMBARKED` → `HELD`) | CustomsOfficer |
| POST | `/port-ops/manifest-entries/{id}/customs-release` | Release an entry to `CLEARED` | CustomsOfficer |
| POST | `/port-ops/baggage-items` | Check a bag (`CHECKED`) | TerminalOperator |
| GET | `/port-ops/baggage-items` | List baggage items | Any authenticated role |
| GET | `/port-ops/baggage-items/{id}` | Get a baggage item | Any authenticated role |
| POST | `/port-ops/baggage-items/{id}/stage` | Stage a bag (`CHECKED` or `RECOVERED` → `STAGED`) | TerminalOperator |
| POST | `/port-ops/baggage-items/{id}/load` | Load a staged bag (`STAGED` → `LOADED`) | TerminalOperator |
| POST | `/port-ops/baggage-items/{id}/report-mistag` | Report a mis-tagged bag (`CHECKED` or `STAGED` → `MISTAGGED`) | TerminalOperator |
| POST | `/port-ops/baggage-items/{id}/recover` | Recover a mis-tagged bag (`MISTAGGED` → `RECOVERED`) | TerminalOperator |
| POST | `/port-ops/baggage-items/{id}/deliver` | Deliver a staged debark bag (`STAGED` → `DELIVERED`) | TerminalOperator |
| POST | `/port-ops/screening-lanes` | Create a screening lane (`CLOSED`) | PortAuthorityAdmin |
| GET | `/port-ops/screening-lanes` | List screening lanes | Any authenticated role |
| GET | `/port-ops/screening-lanes/{id}` | Get a screening lane | Any authenticated role |
| POST | `/port-ops/screening-lanes/{id}/open` | Open a lane with its officer staffing | TerminalOperator |
| POST | `/port-ops/screening-lanes/{id}/close` | Close a lane and clear its staffing | TerminalOperator |
| POST | `/port-ops/port-calls/{id}/customs-cases` | Create the call's customs case (`DRAFT`) | CustomsOfficer |
| GET | `/port-ops/customs-cases` | List customs cases | Any authenticated role |
| GET | `/port-ops/customs-cases/{id}` | Get a customs case | Any authenticated role |
| POST | `/port-ops/customs-cases/{id}/file` | File the case (`DRAFT` or `HELD` → `FILED`) | CustomsOfficer |
| POST | `/port-ops/customs-cases/{id}/hold` | Hold the case (`FILED` → `HELD`) with the disembark cascade | CustomsOfficer |
| POST | `/port-ops/customs-cases/{id}/clear` | Clear the case (`FILED` → `CLEARED`) | CustomsOfficer |
| POST | `/port-ops/port-calls/{id}/service-orders` | Request a service order (`REQUESTED`) | VesselAgent |
| GET | `/port-ops/service-orders` | List service orders | Any authenticated role |
| GET | `/port-ops/service-orders/{id}` | Get a service order | Any authenticated role |
| POST | `/port-ops/service-orders/{id}/approve` | Approve an order (`REQUESTED` → `APPROVED`) | TerminalOperator, Harbormaster |
| POST | `/port-ops/service-orders/{id}/reject` | Reject an order (`REQUESTED` → `REJECTED`) | TerminalOperator, Harbormaster |
| POST | `/port-ops/service-orders/{id}/start` | Start an approved order (`APPROVED` → `IN_PROGRESS`) | TerminalOperator |
| POST | `/port-ops/service-orders/{id}/complete` | Complete an order with actual units (`IN_PROGRESS` → `COMPLETED`) | TerminalOperator |
| POST | `/port-ops/service-orders/{id}/cancel` | Cancel an order (`REQUESTED` or `APPROVED` → `CANCELLED`) | VesselAgent |
| POST | `/port-ops/port-calls/{id}/provisional-invoice` | Generate the call's `PROVISIONAL` invoice (`DRAFT`) | BillingClerk |
| GET | `/port-ops/invoices` | List invoices | Any authenticated role |
| GET | `/port-ops/invoices/{id}` | Get an invoice | Any authenticated role |
| POST | `/port-ops/invoices/{id}/issue` | Issue an invoice (`DRAFT` → `ISSUED`) | BillingClerk |
| POST | `/port-ops/invoices/{id}/settle` | Settle an issued invoice at its exact total (`ISSUED` → `SETTLED`) | BillingClerk |
| POST | `/port-ops/invoices/{id}/dispute` | Dispute an issued invoice (`ISSUED` → `DISPUTED`) | VesselAgent |
| POST | `/port-ops/invoices/{id}/adjustments` | Post a credit adjustment (OCC-guarded; returns the updated invoice) | BillingClerk |
| POST | `/port-ops/transport-slots` | Enqueue a ground-transport slot (`QUEUED`) | TerminalOperator |
| GET | `/port-ops/transport-slots` | List transport slots | Any authenticated role |
| GET | `/port-ops/transport-slots/{id}` | Get a transport slot | Any authenticated role |
| POST | `/port-ops/transport-slots/{id}/dispatch` | Dispatch the head of a class queue (`QUEUED` → `DISPATCHED`) | TerminalOperator |
| POST | `/port-ops/transport-slots/{id}/complete` | Complete a dispatched slot (`DISPATCHED` → `COMPLETED`) | TerminalOperator |
| POST | `/port-ops/transport-slots/{id}/no-show` | Mark a dispatched slot no-show (`DISPATCHED` → `NO_SHOW`) | TerminalOperator |
| POST | `/port-ops/transport-slots/{id}/requeue` | Requeue a no-show slot once (`NO_SHOW` → `QUEUED`) | TerminalOperator |
| POST | `/port-ops/weather-advisories` | Create a weather advisory (`ACTIVE`) | PortAuthorityAdmin |
| GET | `/port-ops/weather-advisories` | List weather advisories | Any authenticated role |
| GET | `/port-ops/weather-advisories/{id}` | Get a weather advisory | Any authenticated role |
| POST | `/port-ops/weather-advisories/{id}/cancel` | Cancel an advisory (`ACTIVE` → `CANCELLED`) | PortAuthorityAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every machine-readable error identifier and its HTTP status. The conditions under which each error is raised are defined in the workflow narratives of §2 and §3, not here.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_VESSEL_SCOPE` | 403 Forbidden |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_STALE_INVOICE_VERSION` | 412 Precondition Failed |
| `ERR_VALIDATION` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_POSTURE_EMERGENCY` | 409 Conflict |
| `ERR_BERTH_NOT_FIT` | 422 Unprocessable Entity |
| `ERR_WASTE_BEFORE_PROVISIONING` | 409 Conflict |
| `ERR_TURNAROUND_TOO_SHORT` | 422 Unprocessable Entity |
| `ERR_WINDOW_NOT_CONTAINED` | 422 Unprocessable Entity |
| `ERR_ADVISORY_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_SERVICE_WINDOW_OUTSIDE_BERTH` | 422 Unprocessable Entity |
| `ERR_BERTH_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_SCREENING_CAPACITY` | 409 Conflict |
| `ERR_APRON_CAPACITY` | 409 Conflict |
| `ERR_QUEUE_WINDOW_FULL` | 409 Conflict |
| `ERR_QUEUE_ORDER` | 409 Conflict |
| `ERR_DUPLICATE_MANIFEST_REF` | 409 Conflict |
| `ERR_DUPLICATE_TAG` | 409 Conflict |
| `ERR_DUPLICATE_CUSTOMS_CASE` | 409 Conflict |
| `ERR_INVOICE_KIND_EXISTS` | 409 Conflict |
| `ERR_REQUEUE_LIMIT` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 409 Conflict |
| `ERR_CONSTRAINED_REQUIRES_HARBORMASTER` | 403 Forbidden |
| `ERR_UNDERPAYMENT` | 422 Unprocessable Entity |
| `ERR_OVERPAYMENT` | 422 Unprocessable Entity |
| `ERR_CREDIT_EXCEEDS_OUTSTANDING` | 422 Unprocessable Entity |
| `ERR_MANIFEST_DIRECTION` | 422 Unprocessable Entity |
| `ERR_OPEN_MISTAGS` | 409 Conflict |
| `ERR_CUSTOMS_NOT_CLEARED` | 409 Conflict |
| `ERR_CUSTOMS_HOLD_ACTIVE` | 409 Conflict |
| `ERR_OPEN_SERVICE_ORDERS` | 409 Conflict |
