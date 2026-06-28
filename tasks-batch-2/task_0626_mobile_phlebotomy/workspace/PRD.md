# Mobile Phlebotomy API — Product Requirements Document

## 1. Introduction

Mobile phlebotomy brings the lab to the patient's door. A clinician orders a blood panel, an operations team schedules a phlebotomist to drive to the patient inside a chosen time window, the draw is performed and labeled at the kitchen table, and the tubes then ride a courier to a reference laboratory (Quest, Labcorp, or similar) for processing. This API governs that entire chain — from order intake and territory-aware routing, through on-site collection and an auditable chain of custody, to lab accessioning, result routing, and the final invoice. The dominant design concern is that physical specimens are irreplaceable: every state transition must be traceable, and a botched draw (a tube with insufficient blood) must reliably trigger a redraw rather than silently disappearing.

The system is built around five operational actors who hand work off to one another in sequence. An ordering clinician opens an order; a dispatcher books it onto a phlebotomist's route, hands over a kit, and dispatches the field collector; the phlebotomist arrives, draws and labels the tubes, and batches them onto a courier manifest; lab operations accession or reject each specimen and release results; and a billing operator issues the invoice. Because each handoff mutates several linked records at once — a redraw, for example, must reopen the order, free the route-day slot, and penalize the phlebotomist — the specification below is precise about every cascade, every fee, and every guard that protects the irreplaceable specimen as it moves through custody.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, response contracts, and cross-cutting principles that apply across every endpoint in the API.

### 2.1. User and Role-Based Access Control

Every request must carry two mandatory HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which the request is made. If either header is missing or malformed, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are present and well-formed but the declared role is not permitted to perform the requested operation, the request is rejected with `ERR_INSUFFICIENT_PERMISSIONS`.

The system recognizes exactly five roles, spelled precisely as follows: `OrderingProvider`, `Dispatcher`, `Phlebotomist`, `LabOps`, and `BillingAgent`. An `OrderingProvider` is the clinician who creates and cancels lab orders and reviews their results and invoices. A `Dispatcher` is the operations coordinator who manages phlebotomists, route days, appointment booking, dispatch, recall, kit assignment, and courier manifests. A `Phlebotomist` is the field collector who arrives on-site, labels and collects specimens, completes the draw, and batches specimens onto a manifest. A `LabOps` operator configures test panels and lab partners, accessions or rejects specimens, and routes results. A `BillingAgent` issues and voids invoices.

Four of the five roles are operator identities not tied to any persisted entity. When `X-User-Role` is `OrderingProvider`, `X-User-ID` is an opaque operator identifier; the server records it as `ordering_provider_id` on the `LabOrder` the provider creates, but it does not compare it to any entity's `id`. When `X-User-Role` is `Dispatcher`, `LabOps`, or `BillingAgent`, `X-User-ID` is likewise an opaque operator identifier; the server may record it (for example, as the `actor_user_id` written onto a chain-of-custody event at each custody hop) but does not compare it to any entity's `id`. By contrast, when `X-User-Role` is `Phlebotomist`, `X-User-ID` is the `id` of the acting `Phlebotomist` entity; ownership checks compare a resource's denormalized `phlebotomist_id` to `X-User-ID`. In particular, the on-site arrival action requires that `X-User-ID` equal the appointment's assigned `phlebotomist_id`; a mismatch is rejected with `ERR_NOT_ASSIGNED_PHLEBOTOMIST`.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter is the number of items to skip and defaults to 0. Unless a specific endpoint states otherwise, list results are sorted by `created_at` in ascending order.

Every list response includes the following four fields inside the envelope's `meta` object: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Most resources in this system are mutable and carry a standard set of system-managed fields. Each such resource has an `id` — a server-minted UUID with no type prefix — a `created_at` timestamp recorded at creation, an `updated_at` timestamp refreshed on every mutation, and an integer `version` that begins at its initial value and increments by one on every mutation. Both `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits. These common fields apply to `TestPanel`, `LabPartner`, `Phlebotomist`, `RouteDay`, `LabOrder`, `Appointment`, `DrawKit`, `Specimen`, `CourierManifest`, `LabResult`, and `Invoice`.

The chain-of-custody event is the one exception. A `ChainOfCustodyEvent` is an append-only, immutable audit record: it carries only an `id` and a `created_at`. It has no `updated_at` and no `version`, because it is never modified after it is written.

Several timestamps are stamped from a **logical server clock** rather than wall-clock time. The clock starts at exactly `2026-01-01T00:00:00Z` at startup and stays at that value until it is explicitly advanced; it never falls back to wall-clock time. A test-driving capability lets an operator advance the clock to a supplied `to_iso8601` instant. The fields stamped from this clock are a specimen's `collected_at_utc` at collection time, a manifest's `picked_up_at_utc` at courier pickup, and a manifest's derived `accession_due_utc`.

### 2.5. Hierarchical Consistency and Cascading Side Effects

Many operations mutate more than one entity at once, and the secondary effects matter as much as the primary one. Whenever a mutation changes a resource, that resource's `updated_at` is refreshed and its `version` is incremented by one — and this is equally true of resources touched only indirectly by a cascade. For example, booking an appointment increments the affected route day's `version`; freeing a route-day slot during a cancellation or redraw increments it again. Each automatic, server-initiated transition that the rules below describe is itself a mutation: it bumps the affected entity's `version` and refreshes its `updated_at` exactly as a client-initiated change would.

Two derived counts must be kept reconciled at all times. A route day's `booked_stop_count` is the number of appointments on that route day in any of the four live statuses `SCHEDULED`, `DISPATCHED`, `ARRIVED`, or `DRAW_COMPLETED`; it rises by one on each booking and falls by one on each cancellation or redraw-driven appointment cancellation. An order's `specimens_accessioned_count` is the number of that order's specimens currently in `ACCESSIONED` status; specimens in `QNS_REJECTED` are never counted, so a rejection that follows a prior accession reduces the reconciled count.

### 2.6. Nested Resource Retrieval and Path Validation

Many endpoints address a resource nested beneath one or more parents in the URL. The system validates every identifier in the path from left to right and rejects the request at the first identifier that does not resolve to an existing resource, using the not-found error specific to that resource type. A request that names a non-existent order before naming an appointment, for instance, fails with `ERR_ORDER_NOT_FOUND` before the appointment is ever looked up. The resource-specific not-found errors are `ERR_PANEL_NOT_FOUND`, `ERR_LAB_PARTNER_NOT_FOUND`, `ERR_PHLEBOTOMIST_NOT_FOUND`, `ERR_ROUTE_DAY_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_APPOINTMENT_NOT_FOUND`, `ERR_SPECIMEN_NOT_FOUND`, `ERR_CUSTODY_EVENT_NOT_FOUND`, `ERR_MANIFEST_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`, and `ERR_KIT_NOT_FOUND`. Foreign-key references supplied in a request body are also validated for existence — the `panel_code`, `lab_partner_id`, `route_day_id`, and `lab_order_id` named in a create or mutation body must resolve to existing resources, again using the resource-specific not-found error.

### 2.7. Validation Ordering

When several checks apply to a single request, they are evaluated in a fixed priority order, so that the earliest applicable failure is the one reported. The order is: first, header presence and well-formedness (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`); second, role permission for the operation (`ERR_INSUFFICIENT_PERMISSIONS`); third, existence of every resource id named in the path, left to right (the resource-specific not-found error); fourth, existence of foreign keys referenced in the body (the resource-specific not-found error); fifth, request-body well-formedness — required fields present, enums valid, integers non-negative, an appointment's window end strictly after its window start, and an insurance order carrying its member id (`ERR_INVALID_REQUEST`); sixth, the optimistic-concurrency version check on appointment booking (`ERR_ROUTE_DAY_VERSION_STALE`); and seventh, the state-legality check that the target resource is in a state from which the requested transition is permitted (the transition-specific conflict error). Business-rule checks that follow — such as panel acceptance, phlebotomist availability, territory matching, capacity, and window conflict — are evaluated after the state check; the specific orderings among them are described alongside the workflows in §3. Notably, on appointment booking the route-day version check runs before any of the route-day business preconditions.

### 2.8. Optimistic Concurrency on Route-Day Booking

Appointment booking is the one operation guarded by optimistic concurrency control. A request to book (or re-book after a redraw) an appointment for an order onto a route day must carry an `expected_route_day_version` field whose value equals the target route day's current `version` at the moment of booking. This field is mandatory on that operation. Because a successful booking increments the route day's `version` (the `booked_stop_count` rises by one), a client that read the route day, then saw another booking land on the same route day before its own request, will be carrying a stale `expected_route_day_version`. In that case the booking is rejected with `ERR_ROUTE_DAY_VERSION_STALE` and an HTTP 412 status, before it can over-subscribe the route day's `stop_capacity`. No other endpoint accepts or requires a version field.

### 2.9. Monetary Precision

All money in the system is expressed in integer cents. Every fee, surcharge, waiver, and total is computed and stored as a whole number of cents, and all arithmetic is performed in cents with no fractional rounding. Fields denominated this way include `base_lab_fee_cents`, `stat_surcharge_cents`, `total_due_cents`, `lab_fee_cents`, `convenience_fee_cents`, `redraw_waiver_cents`, and `total_cents`. Where a formula could in principle produce a negative result, the result is floored at zero, as described with the billing calculations in §3.

## 3. Business Logic & Workflows

### 3.1. Catalog Configuration: Panels and Lab Partners

Before any order can be placed, a `LabOps` operator configures the catalog. A **test panel** is created with a `panel_code` (a unique short code such as CMP14, LIPID, or CBC), a human-readable `name`, a `required_tube_count` giving the number of specimen tubes that constitute a valid draw (at least one), and a `base_lab_fee_cents` value (at least zero) representing the lab-side processing fee. The creator may also set `fasting_required`, a boolean flag recording whether the patient must be fasting at draw time; when omitted it defaults to `false`. A new panel begins life in `ACTIVE` status. A panel may later be retired, moving its `status` from `ACTIVE` to `RETIRED`; a `RETIRED` panel can no longer be ordered.

A **lab partner** represents a reference laboratory such as Quest or Labcorp. It is created with a `name`, a `courier_sla_hours` value (the maximum number of hours allowed from manifest pickup to accession, at least one), and an `accepted_panel_codes` array listing the `panel_code` values the partner is able to process. A partner may also be given a `stat_surcharge_cents` amount (at least zero), the extra lab fee added when an order is flagged STAT priority; this defaults to zero. A new partner begins in `ACTIVE` status. A partner may be suspended, moving its `status` from `ACTIVE` to `SUSPENDED`; a `SUSPENDED` partner cannot accept new courier manifests at pickup time.

### 3.2. Building the Field: Phlebotomists and Route Days

A `Dispatcher` registers a **phlebotomist** with a `full_name` and a `territory_code` (the service territory the collector is certified for, such as SF_BAY). A `certification_active` flag indicates whether the phlebotomist may be dispatched at all; it defaults to `true`. Each phlebotomist also carries a `redraw_strike_count`, which starts at zero and accumulates as described in §3.8, and a `status` that begins at `AVAILABLE`. A phlebotomist's `status` is either `AVAILABLE` or `SUSPENDED`; it becomes `SUSPENDED` once the strike count reaches the suspension threshold, and is otherwise `AVAILABLE`.

A `Dispatcher` opens a **route day** for a specific phlebotomist. A route day records the `phlebotomist_id` of the collector running it (taken from the path), a `territory_code` served by the route, a `service_date` (a calendar date in YYYY-MM-DD form), and a bookable shift bounded by `shift_start_utc` (the earliest bookable appointment start, inclusive) and `shift_end_utc` (the latest bookable appointment end, inclusive). It also carries a `stop_capacity` giving the maximum number of booked appointments the day can hold (at least one), a derived `booked_stop_count` that begins at zero, and a `status` of either `OPEN` or `CLOSED`. A new route day opens in `OPEN`; a `CLOSED` route day rejects new bookings.

A phlebotomist cannot run two overlapping shifts. When a new route day is opened, its shift interval `[shift_start_utc, shift_end_utc]` must not overlap any existing `OPEN` route day belonging to the same phlebotomist, and this comparison uses **closed-interval** semantics: touching endpoints conflict, so a new shift whose start equals an existing open shift's end (or whose end equals an existing open shift's start) is a conflict, because a phlebotomist may not run two shifts that abut. A violation is rejected with `ERR_ROUTE_DAY_SHIFT_OVERLAP`. A route day may later be closed, moving its `status` to `CLOSED`.

### 3.3. Opening an Order

An `OrderingProvider` opens a **lab order** for a patient and panel. The create payload supplies the `patient_full_name`, the `patient_territory_code` (the patient's service territory), the `panel_code` being ordered, the `lab_partner_id` of the partner that will process the specimens, and the `billing_mode`, which is either `INSURANCE` or `SELF_PAY`. An optional `priority` of either `ROUTINE` or `STAT` may be supplied; it defaults to `ROUTINE`, and `STAT` is what causes the partner's stat surcharge to apply. When `billing_mode` is `INSURANCE`, the payload must also include an `insurance_member_id`; an insurance order missing that field is malformed and rejected with `ERR_INVALID_REQUEST`. The server stamps the order's `ordering_provider_id` from `X-User-ID`.

At creation the order's `panel_code` must reference a panel that is `ACTIVE` and whose code appears in the chosen partner's `accepted_panel_codes`. If the ordered panel is `RETIRED`, or if it is not among the partner's accepted codes, the order is rejected with `ERR_PANEL_NOT_ACCEPTED_BY_PARTNER`. A new order enters `ORDERED` status. At this point the server mirrors the ordered panel's `required_tube_count` onto the order as `specimens_required_count`, initializes `specimens_accessioned_count` and `redraw_count` to zero, leaves `appointment_id` unset until an appointment is booked, and stamps a provisional `total_due_cents` (see §3.9). The server also creates a companion `DRAFT` invoice for the order at this time.

An order's `status` is one of `ORDERED`, `SCHEDULED`, `DRAW_COMPLETED`, `REDRAW_REQUIRED`, `RESULTED`, or `CANCELLED`, with `RESULTED` and `CANCELLED` being terminal. An `OrderingProvider` may cancel an order while it is in `ORDERED`, `SCHEDULED`, or `REDRAW_REQUIRED`; a cancel attempt from any other status is rejected with `ERR_ORDER_NOT_CANCELLABLE`. Cancellation moves the order to `CANCELLED`. If the order has an active appointment at the time of cancellation (which is the case from the `SCHEDULED` state), that appointment is moved to `CANCELLED`, the owning route day's `booked_stop_count` is decremented by one, and the route day's `version` is incremented by one as compensation. When the order is cancelled out of `REDRAW_REQUIRED`, there is no active appointment to compensate (the redraw already cancelled it), so only the order's status changes.

### 3.4. Scheduling: Booking an Appointment onto a Route Day

A `Dispatcher` books an **appointment** that places an order's draw onto a route day at a requested time window. The booking payload identifies the `route_day_id`, supplies the requested `window_start_utc` (inclusive) and `window_end_utc` (exclusive, and required to be strictly after the start), and carries the `expected_route_day_version` described in §2.8. The same operation serves both the first booking, advancing the order from `ORDERED` to `SCHEDULED`, and the re-booking after a redraw, advancing it from `REDRAW_REQUIRED` to `SCHEDULED`. In either case the order must be in `ORDERED` or `REDRAW_REQUIRED`; a booking attempt against an order in any other status is rejected with `ERR_ORDER_NOT_SCHEDULABLE`.

Booking is gated by a sequence of route-day checks. The referenced route day must be `OPEN`, or the request fails with `ERR_ROUTE_DAY_CLOSED`. The route day's `territory_code` must equal the order's `patient_territory_code`, or the request fails with `ERR_TERRITORY_MISMATCH`. The route day's current `booked_stop_count` must be strictly less than its `stop_capacity` at booking time, or the request fails with `ERR_ROUTE_DAY_FULL`. And the requested window must fit the day: the half-open interval `[window_start_utc, window_end_utc)` must lie within the route day's `[shift_start_utc, shift_end_utc]` and must not overlap any other booked appointment's window on the same route day. The overlap test uses **half-open** semantics, so back-to-back stops are allowed: one appointment ending exactly when another begins is not a conflict. A window that falls outside the shift or that overlaps an existing booked window is rejected with `ERR_APPOINTMENT_WINDOW_CONFLICT`.

A successful booking creates an appointment in `SCHEDULED` status. The appointment records the `lab_order_id` it fulfills, the `route_day_id` it is booked on, and a `phlebotomist_id` denormalized from the route day's phlebotomist at booking time, together with the requested `window_start_utc` and `window_end_utc`. As side effects, the order's `appointment_id` is set to the new appointment, the order moves to `SCHEDULED`, the route day's `booked_stop_count` rises by one, and the route day's `version` rises by one. An appointment's `status` is one of `SCHEDULED`, `DISPATCHED`, `ARRIVED`, `DRAW_COMPLETED`, or `CANCELLED`, with `DRAW_COMPLETED` and `CANCELLED` terminal.

### 3.5. Equipping and Dispatching the Phlebotomist

Before a draw can happen, a `Dispatcher` assigns a **draw kit** to a scheduled appointment. The kit payload carries a `kit_lot_number` (the manufacturer lot number) and a `tube_count` giving how many empty tubes are loaded (at least one). The kit records its `appointment_id` and begins in `ASSIGNED` status. A kit's `status` is either `ASSIGNED` or `CONSUMED`; it becomes `CONSUMED` when the draw is completed.

Dispatching sends the assigned phlebotomist out. A `Dispatcher` may dispatch an appointment only while it is in `SCHEDULED`, advancing it to `DISPATCHED`; a dispatch attempt from any other state is rejected with `ERR_APPOINTMENT_NOT_DISPATCHABLE`. Two further conditions guard dispatch. First, the assigned phlebotomist must be eligible: the collector's `certification_active` must be `true` and the collector's `status` must be `AVAILABLE`, otherwise the dispatch is rejected with `ERR_PHLEBOTOMIST_UNAVAILABLE`. Second, a draw kit must already be assigned to the appointment whose `tube_count` is at least the order's `specimens_required_count`; if no such kit is assigned, the dispatch is rejected with `ERR_KIT_NOT_ASSIGNED`.

Dispatch is reversible before arrival. A `Dispatcher` may recall an appointment that is currently `DISPATCHED`, reverting it from `DISPATCHED` back to `SCHEDULED` so dispatch can be retried; a recall attempt against an appointment not in `DISPATCHED` is rejected with `ERR_APPOINTMENT_NOT_RECALLABLE`.

### 3.6. On-Site: Arrival, Collection, and the Draw

The field phase belongs to the `Phlebotomist`. Arrival advances the appointment from `DISPATCHED` to `ARRIVED`; an arrival attempt against an appointment not in `DISPATCHED` is rejected with `ERR_APPOINTMENT_NOT_ARRIVABLE`. Arrival is the action gated by phlebotomist identity: the acting `X-User-ID` must equal the appointment's denormalized `phlebotomist_id`, and a mismatch is rejected with `ERR_NOT_ASSIGNED_PHLEBOTOMIST`.

Once on-site, the phlebotomist labels and collects tubes one at a time. Each collection supplies a `tube_label` — a short label printed on the tube, such as T1 or T2 — that must be unique within its lab order; a repeated label on the same order is rejected with `ERR_DUPLICATE_TUBE_LABEL`. Each collected **specimen** is created in `COLLECTED` status with its `collected_at_utc` stamped from the logical clock, and with its `lab_order_id` and `appointment_id` denormalized from the appointment context. A specimen also carries a `courier_manifest_id` (unset until it is batched onto a manifest) and a `status` that is one of `COLLECTED`, `MANIFESTED`, `ACCESSIONED`, or `QNS_REJECTED`, the last two being terminal. The very first collection for a specimen also appends the first chain-of-custody event, described in §3.7.

Completing the draw advances the appointment from `ARRIVED` to `DRAW_COMPLETED`; a complete-draw attempt against an appointment not in `ARRIVED` is rejected with `ERR_APPOINTMENT_NOT_ARRIVED`. Completion is allowed only when exactly `specimens_required_count` specimens exist for the order, all of them in `COLLECTED` status; any other collected count is rejected with `ERR_SPECIMEN_COUNT_MISMATCH`. A successful completion moves the appointment to `DRAW_COMPLETED`, marks the appointment's draw kit `CONSUMED`, and bubbles the owning order up from `SCHEDULED` to `DRAW_COMPLETED`.

### 3.7. Chain of Custody

Every specimen carries an append-only, immutable custody chain that records each hop in its physical journey. A **chain-of-custody event** records the `specimen_id` it concerns, a `prior_event_id` linking to the previous event for that specimen (left unset for the very first event), an `event_type`, the `actor_role` taken from `X-User-Role` at the hop, the `actor_user_id` taken from `X-User-ID` at the hop, and a `sequence_index` giving the event's zero-based position in the specimen's chain. The `event_type` is one of `COLLECTED`, `MANIFESTED`, `ACCESSIONED`, or `REJECTED_QNS`.

The chain is built automatically as the specimen moves. When a specimen is first collected, the system appends its first event with type `COLLECTED` and `sequence_index` zero. When the specimen is batched onto a manifest, an event of type `MANIFESTED` is appended, linked to the prior event. When the specimen is accessioned at the lab, an `ACCESSIONED` event is appended; when it is rejected for insufficient quantity, a `REJECTED_QNS` event is appended. Because these records are immutable, they carry only an `id` and a `created_at` and are never updated.

### 3.8. Manifesting, Courier Pickup, and Accessioning

After the draw, the `Phlebotomist` batches collected specimens onto a **courier manifest** bound for the lab. A `Dispatcher` first opens a manifest with a `lab_partner_id` (the partner it is routed to) and a `territory_code` (the territory its specimens were collected in). The manifest begins in `BUILDING` status with a `specimen_count` of zero, a `picked_up_at_utc` and an `accession_due_utc` that remain unset until pickup, and a `status` that is one of `BUILDING`, `IN_TRANSIT`, or `DELIVERED`.

Adding a collected specimen to a manifest is performed by the phlebotomist and identifies the `specimen_id` to batch. The specimen must be in `COLLECTED`, or the request fails with `ERR_SPECIMEN_NOT_MANIFESTABLE`. The manifest must be in `BUILDING`, or the request fails with `ERR_MANIFEST_NOT_BUILDING`. The manifest's `territory_code` must equal the collection territory of the specimen's order, or the request fails with `ERR_TERRITORY_MISMATCH`. And the manifest's `lab_partner_id` must equal the `lab_partner_id` on the specimen's lab order, or the request fails with `ERR_LAB_PARTNER_MISMATCH`. On success, the specimen's `courier_manifest_id` is set, the specimen moves from `COLLECTED` to `MANIFESTED`, the manifest's `specimen_count` rises by one, and a `MANIFESTED` custody event is appended linked to the specimen's prior event.

A `Dispatcher` records courier pickup, which starts the lab's SLA clock. Pickup is allowed only when the manifest is `BUILDING`, or it fails with `ERR_MANIFEST_NOT_BUILDING`; the manifest must hold at least one specimen, or it fails with `ERR_MANIFEST_EMPTY`; and the routed partner must be `ACTIVE`, or it fails with `ERR_LAB_PARTNER_SUSPENDED`. On a successful pickup, the manifest's `picked_up_at_utc` is set to the logical clock, the manifest moves from `BUILDING` to `IN_TRANSIT`, and the manifest's `accession_due_utc` is set to the pickup instant plus the partner's `courier_sla_hours` whole hours. The manifest's `specimen_count` reflects the number of its specimens that are in `MANIFESTED` or `ACCESSIONED` status.

At the lab, a `LabOps` operator accessions each specimen. Accessioning is allowed only when the specimen is `MANIFESTED`, or it fails with `ERR_SPECIMEN_NOT_ACCESSIONABLE`, and only when the parent manifest is `IN_TRANSIT`, or it fails with `ERR_MANIFEST_NOT_IN_TRANSIT`. A successful accession moves the specimen from `MANIFESTED` to `ACCESSIONED`, raises the owning order's `specimens_accessioned_count` by one, and appends an `ACCESSIONED` custody event. After the move, if every specimen on the manifest is now in either `ACCESSIONED` or `QNS_REJECTED`, the manifest bubbles up from `IN_TRANSIT` to `DELIVERED`.

A `LabOps` operator may instead reject a specimen for quantity-not-sufficient. Rejection is allowed only when the specimen is `MANIFESTED`, or it fails with `ERR_SPECIMEN_NOT_REJECTABLE`, and only when the parent manifest is `IN_TRANSIT`, or it fails with `ERR_MANIFEST_NOT_IN_TRANSIT`. A successful rejection moves the specimen from `MANIFESTED` to `QNS_REJECTED` and appends a `REJECTED_QNS` custody event. Symmetrically with accessioning, after the move, if every specimen on the manifest is now in either `ACCESSIONED` or `QNS_REJECTED`, the manifest bubbles up to `DELIVERED`. A QNS rejection additionally drives the redraw cascade described in §3.9 when the owning order has already completed its draw.

### 3.9. The Redraw Cascade and Phlebotomist Strikes

A quantity-not-sufficient rejection has consequences that ripple outward when it happens to an order that has already completed its draw. If, at the moment of a QNS rejection, the owning order is in `DRAW_COMPLETED`, the order automatically transitions from `DRAW_COMPLETED` to `REDRAW_REQUIRED`, and a chain of compensating effects follows in order. The order's `redraw_count` rises by one. The order's `total_due_cents` is recomputed (see §3.10), now reflecting the accrued redraw. The order's `specimens_accessioned_count` is recomputed to exclude the now-rejected specimen. The order's owning appointment is moved to `CANCELLED`, which decrements the route day's `booked_stop_count` by one and increments the route day's `version` by one. Finally, a strike accrues to the phlebotomist who performed the draw: the phlebotomist denormalized on the order's current owning appointment has their `redraw_strike_count` raised by one, and if that count reaches three, the phlebotomist's `status` becomes `SUSPENDED`; otherwise it remains `AVAILABLE`. The suspension threshold is three strikes — the third QNS-attributable redraw is what suspends a collector.

After a redraw, the order sits in `REDRAW_REQUIRED` with no active appointment, awaiting either re-booking (§3.4) or cancellation (§3.3). Re-booking runs exactly the same route-day guards as a first booking: the order must be in `REDRAW_REQUIRED` (otherwise `ERR_ORDER_NOT_SCHEDULABLE`), the route day must be `OPEN` (otherwise `ERR_ROUTE_DAY_CLOSED`), territories must match (otherwise `ERR_TERRITORY_MISMATCH`), the route day must have spare capacity (otherwise `ERR_ROUTE_DAY_FULL`), and the requested window must not overlap (otherwise `ERR_APPOINTMENT_WINDOW_CONFLICT`). A successful re-booking creates a fresh appointment in `SCHEDULED`, updates the order's `appointment_id`, returns the order to `SCHEDULED`, raises the route day's `booked_stop_count` by one, and increments the route day's `version` by one.

### 3.10. Billing: The Estimate, the Invoice, and the Two Variants

Two distinct money figures live in this system, and they are computed by the same arithmetic at two different moments. The order's `total_due_cents` is a **forward-looking estimate** stamped on the order, while the invoice's `total_cents` is the **chronological final** figure computed when the invoice is issued. They can diverge: the estimate is first stamped at order creation when `redraw_count` is zero (so it carries no redraw waiver), whereas the final invoice reflects whatever redraws actually accrued between order creation and issue.

The lab-fee component is computed the same way under both billing modes: the `lab_fee_cents` is the panel's `base_lab_fee_cents`, plus the partner's `stat_surcharge_cents` when the order's `priority` is `STAT`, and nothing extra when the priority is `ROUTINE`.

Under **self-pay** billing, the patient bears the full lab fee plus a convenience fee, less any redraw waiver. The convenience fee is a flat base of 3,500 cents plus a per-extra-tube surcharge of 500 cents, where the number of extra tubes is the panel's `required_tube_count` minus one but never below zero; so `convenience_fee_cents` equals 3,500 cents plus 500 cents times the greater of zero and `required_tube_count` minus one. The redraw waiver credits 1,000 cents per redraw, but the credit can never exceed the convenience fee: `redraw_waiver_cents` is the smaller of the convenience fee and 1,000 cents times the order's `redraw_count`. The self-pay total is the lab fee plus the convenience fee minus the waiver, floored at zero: `total_cents` equals the greater of zero and `lab_fee_cents` plus `convenience_fee_cents` minus `redraw_waiver_cents`.

Under **insurance** billing, the insurer covers the lab fee, so the patient owes only the convenience fee less any waiver. The `lab_fee_cents` is still computed and stored on the invoice exactly as above, but it is excluded from the patient total. The insurance convenience fee is a flat 2,500 cents regardless of tube count, because the insurer reimburses processing per panel rather than per tube; tube count is ignored. The redraw waiver under insurance credits 2,500 cents per redraw, again capped at the convenience fee: `redraw_waiver_cents` is the smaller of the convenience fee and 2,500 cents times the order's `redraw_count` — which means a single redraw fully waives the insurance convenience fee. The insurance patient total excludes the lab fee entirely: `total_cents` equals the greater of zero and `convenience_fee_cents` minus `redraw_waiver_cents`.

The order's `total_due_cents` estimate runs this same variant arithmetic against the order's current `redraw_count`. At order creation the count is zero, so the estimate carries no waiver. After a QNS-driven redraw bumps the count, the estimate is recomputed and now reflects the accrued waiver, diverging from the at-creation estimate for the same panel and partner inputs. The order's `billing_mode`, `priority`, the ordered panel, and the partner are the inputs throughout.

### 3.11. Results and Invoicing

Once specimens are accessioned, a `LabOps` operator routes **results** to the provider and portal. Results may be posted only when the order is in `DRAW_COMPLETED`, or the request fails with `ERR_ORDER_NOT_RESULTABLE`, and only when the order's `specimens_accessioned_count` equals its `specimens_required_count`, or the request fails with `ERR_SPECIMENS_NOT_ACCESSIONED`. The post supplies a `result_value` (the encoded result payload). On success the system creates a **lab result** in `PENDING_RELEASE` status carrying the `lab_order_id`, a `lab_partner_id` copied from the order, the `result_value`, and two release flags — `released_to_provider` and `released_to_portal` — both initially false and set true once routed to the ordering provider and the patient portal respectively. The result's `status` is either `PENDING_RELEASE` or `RELEASED`. Posting results moves the order from `DRAW_COMPLETED` to `RESULTED`, which is terminal.

The **invoice** created alongside the order in §3.3 carries the `lab_order_id`, a `billing_mode` copied from the order at invoice time, and the computed components `lab_fee_cents`, `convenience_fee_cents`, `redraw_waiver_cents` (defaulting to zero), and `total_cents`. Its `status` is one of `DRAFT`, `ISSUED`, or `VOID`. A `BillingAgent` issues the invoice, which is permitted only while the invoice is in `DRAFT` (otherwise `ERR_INVOICE_NOT_ISSUABLE`) and only while the owning order is `RESULTED` (otherwise `ERR_ORDER_NOT_RESULTED`). Issuing recomputes `lab_fee_cents`, `convenience_fee_cents`, `redraw_waiver_cents`, and `total_cents` via the order's active billing variant as described in §3.10, then moves the invoice from `DRAFT` to `ISSUED`. A `BillingAgent` may instead void a draft invoice, which is permitted only while it is in `DRAFT` (otherwise `ERR_INVOICE_NOT_VOIDABLE`) and moves it from `DRAFT` to `VOID`.

## 4. Endpoint Definitions

Operations that create a new resource return a `201 Created` status code. Operations that modify an existing resource, including state-transition actions and list or fetch reads, return a `200 OK` status code. All endpoints require the `X-User-ID` and `X-User-Role` headers described in §2.1.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/test-panels` | Create a test panel | LabOps |
| GET | `/test-panels` | List test panels (optional `panel_code` filter) | OrderingProvider, Dispatcher, Phlebotomist, LabOps, BillingAgent |
| GET | `/test-panels/{id}` | Get a test panel | OrderingProvider, Dispatcher, Phlebotomist, LabOps, BillingAgent |
| POST | `/test-panels/{id}/retire` | Retire a panel so it can no longer be ordered | LabOps |
| POST | `/lab-partners` | Create a lab partner | LabOps |
| GET | `/lab-partners` | List lab partners | OrderingProvider, Dispatcher, Phlebotomist, LabOps, BillingAgent |
| GET | `/lab-partners/{id}` | Get a lab partner | OrderingProvider, Dispatcher, Phlebotomist, LabOps, BillingAgent |
| POST | `/lab-partners/{id}/suspend` | Suspend a lab partner | LabOps |
| POST | `/phlebotomists` | Register a phlebotomist | Dispatcher |
| GET | `/phlebotomists` | List phlebotomists (optional `territory_code` filter) | Dispatcher, LabOps |
| GET | `/phlebotomists/{id}` | Get a phlebotomist | Dispatcher, LabOps, Phlebotomist |
| POST | `/phlebotomists/{id}/route-days` | Open a route day for a phlebotomist | Dispatcher |
| GET | `/phlebotomists/{id}/route-days` | List a phlebotomist's route days (optional `service_date` filter) | Dispatcher, LabOps |
| GET | `/route-days/{id}` | Get a route day | Dispatcher, LabOps |
| GET | `/route-days/{id}/appointments` | List appointments booked on a route day | Dispatcher, LabOps |
| POST | `/route-days/{id}/close` | Close a route day to new bookings | Dispatcher |
| POST | `/lab-orders` | Create a lab order | OrderingProvider |
| GET | `/lab-orders` | List lab orders (optional `status`, `lab_partner_id`, `appointment_id` filters) | OrderingProvider, Dispatcher, LabOps, BillingAgent |
| GET | `/lab-orders/{id}` | Get a lab order | OrderingProvider, Dispatcher, Phlebotomist, LabOps, BillingAgent |
| POST | `/lab-orders/{id}/appointments` | Book or re-book an appointment for the order | Dispatcher |
| GET | `/lab-orders/{id}/appointments` | List appointments for an order | OrderingProvider, Dispatcher, Phlebotomist, LabOps |
| GET | `/lab-orders/{id}/specimens` | List specimens for an order (optional `status` filter) | OrderingProvider, Dispatcher, Phlebotomist, LabOps |
| GET | `/lab-orders/{id}/results` | List results for an order | OrderingProvider, LabOps, BillingAgent |
| GET | `/lab-orders/{id}/invoices` | List invoices for an order | OrderingProvider, BillingAgent |
| POST | `/lab-orders/{id}/results` | Route results once specimens are accessioned | LabOps |
| POST | `/lab-orders/{id}/cancel` | Cancel an order and compensate any active appointment | OrderingProvider |
| GET | `/appointments/{id}` | Get an appointment | OrderingProvider, Dispatcher, Phlebotomist, LabOps |
| POST | `/appointments/{id}/kit` | Assign a draw kit to a scheduled appointment | Dispatcher |
| GET | `/appointments/{id}/kit` | List the appointment's draw kits | Dispatcher, Phlebotomist, LabOps |
| POST | `/appointments/{id}/dispatch` | Dispatch the assigned phlebotomist | Dispatcher |
| POST | `/appointments/{id}/recall` | Recall a dispatched appointment back to scheduled | Dispatcher |
| POST | `/appointments/{id}/arrive` | Mark arrival on-site | Phlebotomist |
| POST | `/appointments/{id}/specimens` | Label and collect a specimen tube | Phlebotomist |
| GET | `/appointments/{id}/specimens` | List specimens collected at an appointment | Dispatcher, Phlebotomist, LabOps |
| POST | `/appointments/{id}/complete-draw` | Complete the draw once all tubes are collected | Phlebotomist |
| GET | `/specimens/{id}` | Get a specimen | Dispatcher, Phlebotomist, LabOps |
| GET | `/specimens/{id}/custody-events` | List a specimen's chain-of-custody events | Dispatcher, Phlebotomist, LabOps, OrderingProvider |
| GET | `/custody-events/{id}` | Get a single custody event | Dispatcher, Phlebotomist, LabOps, OrderingProvider |
| GET | `/custody-events` | List custody events (optional `specimen_id`, `prior_event_id` filters) | Dispatcher, Phlebotomist, LabOps, OrderingProvider |
| POST | `/specimens/{id}/accession` | Accession a manifested specimen | LabOps |
| POST | `/specimens/{id}/reject-qns` | Reject a manifested specimen for quantity-not-sufficient | LabOps |
| POST | `/courier-manifests` | Open a courier manifest for a lab partner and territory | Dispatcher |
| GET | `/courier-manifests` | List courier manifests (optional `lab_partner_id`, `status` filters) | Dispatcher, LabOps |
| GET | `/courier-manifests/{id}` | Get a courier manifest | Dispatcher, LabOps |
| GET | `/courier-manifests/{id}/specimens` | List specimens on a manifest | Dispatcher, LabOps |
| POST | `/courier-manifests/{id}/add-specimen` | Batch a collected specimen onto a building manifest | Phlebotomist |
| POST | `/courier-manifests/{id}/pickup` | Record courier pickup; manifest goes in-transit | Dispatcher |
| GET | `/lab-results/{id}` | Get a single lab result | OrderingProvider, LabOps, BillingAgent |
| GET | `/lab-results` | List lab results (optional `lab_partner_id`, `lab_order_id` filters) | OrderingProvider, LabOps, BillingAgent |
| GET | `/invoices/{id}` | Get an invoice with computed fee breakdown | OrderingProvider, BillingAgent |
| POST | `/invoices/{id}/issue` | Issue the invoice; recomputes fees | BillingAgent |
| POST | `/invoices/{id}/void` | Void a draft invoice | BillingAgent |
| POST | `/_clock/set_current_utc` | Set the server logical clock | LabOps, Dispatcher |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_PANEL_NOT_FOUND` | 404 Not Found |
| `ERR_LAB_PARTNER_NOT_FOUND` | 404 Not Found |
| `ERR_PHLEBOTOMIST_NOT_FOUND` | 404 Not Found |
| `ERR_ROUTE_DAY_NOT_FOUND` | 404 Not Found |
| `ERR_ORDER_NOT_FOUND` | 404 Not Found |
| `ERR_APPOINTMENT_NOT_FOUND` | 404 Not Found |
| `ERR_SPECIMEN_NOT_FOUND` | 404 Not Found |
| `ERR_CUSTODY_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_MANIFEST_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_KIT_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_DUPLICATE_TUBE_LABEL` | 409 Conflict |
| `ERR_ROUTE_DAY_VERSION_STALE` | 412 Precondition Failed |
| `ERR_ORDER_NOT_SCHEDULABLE` | 409 Conflict |
| `ERR_ORDER_NOT_RESULTABLE` | 409 Conflict |
| `ERR_ORDER_NOT_RESULTED` | 409 Conflict |
| `ERR_ORDER_NOT_CANCELLABLE` | 409 Conflict |
| `ERR_SPECIMENS_NOT_ACCESSIONED` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_DISPATCHABLE` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_RECALLABLE` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_ARRIVABLE` | 409 Conflict |
| `ERR_APPOINTMENT_NOT_ARRIVED` | 409 Conflict |
| `ERR_NOT_ASSIGNED_PHLEBOTOMIST` | 403 Forbidden |
| `ERR_KIT_NOT_ASSIGNED` | 409 Conflict |
| `ERR_SPECIMEN_COUNT_MISMATCH` | 409 Conflict |
| `ERR_ROUTE_DAY_CLOSED` | 409 Conflict |
| `ERR_ROUTE_DAY_FULL` | 409 Conflict |
| `ERR_TERRITORY_MISMATCH` | 409 Conflict |
| `ERR_APPOINTMENT_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_ROUTE_DAY_SHIFT_OVERLAP` | 409 Conflict |
| `ERR_SPECIMEN_NOT_MANIFESTABLE` | 409 Conflict |
| `ERR_SPECIMEN_NOT_ACCESSIONABLE` | 409 Conflict |
| `ERR_SPECIMEN_NOT_REJECTABLE` | 409 Conflict |
| `ERR_MANIFEST_NOT_BUILDING` | 409 Conflict |
| `ERR_MANIFEST_NOT_IN_TRANSIT` | 409 Conflict |
| `ERR_MANIFEST_EMPTY` | 409 Conflict |
| `ERR_LAB_PARTNER_SUSPENDED` | 409 Conflict |
| `ERR_LAB_PARTNER_MISMATCH` | 409 Conflict |
| `ERR_PANEL_NOT_ACCEPTED_BY_PARTNER` | 409 Conflict |
| `ERR_PHLEBOTOMIST_UNAVAILABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_ISSUABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_VOIDABLE` | 409 Conflict |
