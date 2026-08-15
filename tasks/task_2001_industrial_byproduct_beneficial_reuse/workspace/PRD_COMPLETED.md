# Industrial Byproduct Brokerage API — Product Requirements Document

## 1. Introduction

Industrial plants produce continuous streams of residual material — fly ash from combustion, slag from smelting, gypsum from scrubbers, foundry sand, biosolids — much of which can be beneficially reused as cement additive, road base, soil amendment, or mine reclamation fill instead of being landfilled. The economics of that diversion are fragile: a generator must prove its material is chemically consistent, a regulator in each destination state must accept the reuse plan, a buyer must commit to receiving tonnage that meets its quality specification, and someone must pay for freight that can easily exceed the material's market value. This document specifies the Industrial Byproduct Brokerage API, the system of record that sits in the middle of those transactions and makes them auditable.

The API governs the full commercial and regulatory lifecycle: onboarding of generator and offtaker organizations, laboratory characterization of byproduct streams, per-state reuse-eligibility determinations filed and adjudicated under segregation of duties, state permits and notifications, supply agreements and offtake commitments with monthly quotas, and the shipment pipeline from booking through dispatch, delivery, acceptance, rejection, reconditioning, and disposal. Money is settled twice per load — a provisional estimate at booking and a final moisture-adjusted settlement at acceptance — and every accepted ton accrues sustainability credits that are tracked as a ledger and re-reported under a stricter attested variant for regulatory filings. Buffer storage, an append-only market price index, and a controllable logical clock complete the platform.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply to every endpoint of the API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The system recognizes exactly five roles, spelled as follows: `Generator`, `Offtaker`, `BrokerOps`, `ComplianceOfficer`, and `PlatformAdmin`. A request with a missing header, or whose declared role is not one of these five, is rejected with `ERR_UNAUTHENTICATED`. A well-authenticated request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN`.

Two of the roles are entity-backed. When `X-User-Role` is `Generator`, `X-User-ID` is the `id` of the acting Generator organization; ownership checks on any resource that references a Generator compare the resource's `generator_id` field to `X-User-ID`, and a mismatch is rejected with `ERR_OWNERSHIP_MISMATCH`. When `X-User-Role` is `Offtaker`, `X-User-ID` is likewise the `id` of the acting Offtaker organization, and ownership checks compare the resource's `offtaker_id` field to `X-User-ID`. This ownership rule reaches across aggregate boundaries: a Generator may register streams, submit characterizations, create supply agreements, and book or act on shipments only for its own organization, and an Offtaker may create offtake commitments and act on deliveries only for commitments it owns. For shipment-level writes the owned resource is reached through the commercial records the shipment references: the Generator side compares the `generator_id` of the supply agreement — the one named by the booking payload's `supply_agreement_id` at booking time, or the one referenced by the acted-upon shipment for dispatch, recondition, redeliver, dispose, and cancel — and the Offtaker side compares the `offtaker_id` of the commitment referenced by the acted-upon shipment for deliver, accept, and reject.

The remaining three roles are opaque operator identities not tied to any persisted entity. When `X-User-Role` is `BrokerOps`, `X-User-ID` is an operator identifier; the server records it (for example, as `published_by_user_id` on a price index entry) but never compares it to any entity's `id`. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is similarly opaque; it is stamped onto eligibility determinations as `filed_by_user_id` or `approved_by_user_id` and is compared only against each other for segregation-of-duties enforcement (see §3.2). When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is opaque and the role controls only the logical clock described in §2.4. All five roles may call every read endpoint; write privileges are segregated per the endpoint table in §4.

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

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_` followed by twenty random alphanumeric characters.
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
- Requests to undefined paths are rejected with 404 `ERR_NOT_FOUND` in this same envelope.

---

### 2.3. Pagination

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned; it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100 — an out-of-range integer is clamped to the nearest bound rather than rejected, while a non-integer value is rejected with `ERR_INVALID_REQUEST`. The `offset` parameter skips that many items from the start of the result set and defaults to 0; a negative integer is clamped to 0 and a non-integer value is rejected with `ERR_INVALID_REQUEST`. Unless otherwise specified, every list endpoint returns resources sorted by creation timestamp in ascending order, with ties on identical timestamps broken by creation (insertion) order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. The Logical Clock and Time-Driven Reconciliation

Every date comparison in the system — agreement terms, eligibility windows, permit validity, reservation windows, monthly counters, and price effectiveness — is evaluated against a server-side **logical clock**, never against wall-clock time. Before any client has set it, the logical clock reads exactly 2026-08-01T00:00:00Z, and the server must never fall back to wall-clock time under any circumstance. A test-driving capability restricted to `PlatformAdmin` sets the clock: the request supplies a `to_iso8601` instant — either a full ISO 8601 datetime (a naive value, without offset, is read as UTC) or a bare ISO date, which is read as midnight UTC, with anything unparseable rejected as `ERR_INVALID_REQUEST` — and the clock may be set to any such instant, forward or backward, with no monotonicity enforced. The response reports the new value as `current_utc`, echoing the supplied `to_iso8601` string verbatim. Once set, every rule in this document that says "the current logical date" refers to this clock.

Two lifecycle expirations are applied **lazily** against that clock, at the moment a record is read or referenced rather than by any background job. A reuse-eligibility determination in `APPROVED` or `SUSPENDED` status whose `valid_until` date has been reached or passed by the current logical date transitions to `EXPIRED`, which is terminal. A state permit in `ACTIVE` status transitions to `EXPIRED` once the current logical date is later than its `expires_on` day. Listing endpoints for determinations and permits apply the same lazy reconciliation before returning their collections.

Month-to-date commercial counters reconcile lazily as well. Each supply agreement carries `booked_month_to_date_tons` and `delivered_month_to_date_tons`, and each offtake commitment carries `accepted_month_to_date_tons`; each such counter set is stamped with a `counter_month` in YYYY-MM form identifying the logical month the counters belong to. At the start of any read or mutation that touches one of these counters, if the record's `counter_month` differs from the current logical month, the counters are reset to zero and `counter_month` is re-stamped to the current month (an agreement's `fulfillment_status` is reset to `UNMET` in the same refresh). This rollover is a derived-field refresh, not a business mutation: it does not increment `version` and does not refresh `updated_at`. One counter is exempt from rollover — a commitment's `cumulative_rejected_tons` is a lifetime total and never resets.

### 2.5. Common Resource Properties

Primary resources — generators, offtakers, streams, characterization profiles, eligibility determinations, state permits, supply agreements, offtake commitments, shipments, storage facilities, and storage reservations — share a standard set of system-managed fields:

- `id` (string): a unique, server-generated identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource.
- `version` (integer): a system-managed integer that starts at 1 on creation and increments by one on every mutation, including automatic reconciliations such as counter updates, status flips, and inventory adjustments.

Two resources are append-only ledger records and carry only `id` and `created_at`: the market price index entry and the sustainability credit entry. Both `updated_at` and `version` are absent from these two resources — they are never modified after creation.

### 2.6. Hierarchical Consistency and Cascading Mutations

State changes propagate upward and outward to keep the aggregate hierarchy coherent. Verification of a laboratory characterization bubbles up to its owning stream; approval of an eligibility determination bubbles up similarly. Commercially, a destination rejection can cascade: it may suspend the receiving commitment, which in turn cancels every still-booked sibling shipment, and each of those cancellations releases quota back onto its supply agreement. Acceptance and voiding of a load both post entries into the sustainability credit ledger, and each posting recomputes the generator's credit balance and tier. Every one of these automatic reconciliations mutates the affected resource: its `updated_at` is refreshed and its `version` increments by one, so a client watching any level of the hierarchy can observe the change. The single exception is the monthly counter rollover of §2.4, which touches neither field.

### 2.7. Nested Resource Retrieval

Requests that target nested resources are validated strictly from left to right. When a path contains more than one resource identifier — for example, a stream followed by one of its characterizations or eligibility determinations — the existence of each identifier is confirmed in path order, and the request is rejected with a 404 `ERR_NOT_FOUND` for the first identifier that does not resolve, before later segments are even examined. The same discipline applies to creation under a parent, subject to the pipeline order of §2.10: ownership scoping against the parent (stage 3, when the parent exists) and child-payload well-formedness (stage 4) are evaluated before the parent's existence is confirmed (stage 5), so a malformed child payload draws `ERR_INVALID_REQUEST` even when the parent identifier does not resolve.

### 2.8. Units, Precision, and Rounding

All monetary amounts are represented as integer cents; wherever a monetary multiplication produces a fraction, the result is rounded half-up to whole cents at the point the rule specifies, and never earlier. Settlement tonnage is rounded half-up to three decimal places. Sustainability credit amounts are rounded half-up to two decimal places. Percentages travel as plain numbers — a moisture value of 12.5 means 12.5 percent — and date comparisons are made at day granularity against the logical clock. Freight calculation rounds exactly once, at the generator-share multiplication, as detailed in §3.4.

### 2.9. Optimistic Concurrency Control

Exactly one write endpoint participates in optimistic concurrency control: booking a new shipment. A booking request must carry `expected_supply_agreement_version`, a non-optional field holding the `version` of the target supply agreement as the client last observed it. If that value does not match the agreement's current `version`, the booking is rejected with `ERR_STALE_AGREEMENT_VERSION` and HTTP status 412. This captures the case where another writer has just booked or cancelled a load — both of which mutate `booked_month_to_date_tons` and advance the agreement's version — so the current writer's view of remaining monthly quota is stale and must not silently overwrite it. No other endpoint accepts a version field.

### 2.10. The Validation Pipeline

Every request passes through a fixed validation pipeline, and an earlier failure masks all later checks. The stages run in this order. First, authentication: the `X-User-ID` and `X-User-Role` headers must be present and the role must be declared, else `ERR_UNAUTHENTICATED`. Second, authorization: the acting role must be permitted on the endpoint, else `ERR_FORBIDDEN`. Third, identity scoping: entity-backed ownership for Generator and Offtaker writes (`ERR_OWNERSHIP_MISMATCH`), and segregation of duties on eligibility adjudication (`ERR_SEGREGATION_OF_DUTIES`). Fourth, body well-formedness: required fields present, enum values within their declared sets, numeric ranges respected, dates in ISO format — violations yield `ERR_INVALID_REQUEST`, while unknown computed or system-managed fields supplied in the input are ignored rather than rejected. A request body that is not a JSON object — including an absent body on an endpoint whose payload has required fields — is itself an `ERR_INVALID_REQUEST`. Fields validated as integers accept integral JSON numbers, and a boolean is never accepted as a number. Numeric fields carry range checks only where this document states them; measured and specification values (`declared_moisture_pct`, `ph`, `arsenic_ppm`, `lead_ppm`, `moisture_pct_measured`, `max_moisture_pct`, `max_arsenic_ppm`, `loading_moisture_pct`, and the destination readings) accept any JSON number without range validation. Free-form strings — names, emails, permit numbers, and every state or region code — are checked only for non-emptiness; no two-letter, format, or jurisdiction-list validation is applied. Fifth, every resource referenced by a path parameter must exist, else `ERR_NOT_FOUND`. Sixth, every foreign key referenced in the request body — such as `generator_id`, `stream_id`, `supply_agreement_id`, `offtake_commitment_id`, or `facility_id` — must resolve to an existing entity, else `ERR_FK_NOT_FOUND`.

Only after those existence stages do state and business rules fire, again in fixed order. Seventh, the optimistic concurrency check of §2.9 (`ERR_STALE_AGREEMENT_VERSION`). Eighth, state eligibility: the requested transition must be declared from the target resource's current state — attempting any action from a state where it is not defined, including any terminal state, yields `ERR_INVALID_STATE` — and, for booking and dispatch specifically, the agreement and commitment must be `ACTIVE`, yielding `ERR_AGREEMENT_NOT_ACTIVE` or `ERR_COMMITMENT_NOT_ACTIVE` respectively. Ninth, dispatch safety gates (`ERR_REUSE_NOT_ELIGIBLE`, then `ERR_PERMIT_REQUIRED`). Tenth, temporal windows (`ERR_OUTSIDE_AGREEMENT_TERM`, `ERR_ELIGIBILITY_WINDOW_OVERLAP`, `ERR_ELIGIBILITY_WINDOW_PAST`, `ERR_RESERVATION_WINDOW_INVALID`). Eleventh, business constraints (`ERR_DUPLICATE_PERMIT`, `ERR_MATERIAL_NOT_ACCEPTED`, `ERR_STORAGE_CAPACITY_EXCEEDED`, `ERR_QUALITY_OUT_OF_SPEC`). Twelfth, referential business rules (`ERR_STREAM_NOT_CHARACTERIZED`, `ERR_DESTINATION_NOT_SERVED`, `ERR_STREAM_MISMATCH`). Finally, thirteenth, the fiscal gates of booking (`ERR_COMMITMENT_EXCEEDED`, `ERR_PRICE_INDEX_GAP`).

## 3. Business Logic & Workflows

### 3.1. Onboarding Organizations, Streams, and Laboratory Characterization

A `BrokerOps` operator opens the commercial graph by registering the two principal organizations. Registering a **Generator** requires its `legal_name`, the two-letter `hq_state_code` of its headquarters, and a `contact_email`; a new generator begins with `total_credits` of 0.0 and a `credit_tier` of `STANDARD`. Registering an **Offtaker** requires its `legal_name` and `hq_state_code` plus `receiving_state_codes`, the list of two-letter state codes where the buyer is able to receive material — a list later enforced at commitment time (§3.3). Both organizations and all other registered resources are readable by every role.

With an organization in place, a Generator registers a **byproduct stream**. The creation payload carries `generator_id` — which must equal the acting Generator's own id, or the request fails ownership with `ERR_OWNERSHIP_MISMATCH` — along with the stream's `material_type`, one of `FLY_ASH`, `SLAG`, `GYPSUM`, `FOUNDRY_SAND`, or `BIOSOLIDS`; the generator-declared typical `declared_moisture_pct`; and the `expected_tons_per_month` production forecast, a positive integer. A new stream starts in `DRAFT` status, meaning it cannot yet support contracts. The stream catalogue can be listed with optional `generator_id`, `status`, and `material_type` filters.

Before a stream can be contracted, its material must be characterized by a laboratory. The owning Generator submits a **characterization profile** for the stream, supplying the testing laboratory's `lab_name`, the ISO date the sample was `sampled_on`, and the measured values `ph`, `arsenic_ppm`, `lead_ppm`, and `moisture_pct_measured`; the profile's `stream_id` is taken from the request path rather than the body. A new profile starts in `SUBMITTED` status, and a stream's profiles can be listed under the stream.

Verification is the broker's desk. A `BrokerOps` operator may verify a submitted profile, moving it from `SUBMITTED` to `VERIFIED`; when that happens and the owning stream is still in `DRAFT`, the stream bubbles up to `CHARACTERIZED`, refreshing its `updated_at` and incrementing its `version`. Alternatively the operator may reject the profile, moving it from `SUBMITTED` to `REJECTED` and storing the payload's `reason` as the profile's `rejection_reason` (which is null in every other status). Both verification and rejection are only declared from `SUBMITTED` — either action against an already-decided profile is rejected with `ERR_INVALID_STATE` — and both outcomes are terminal for the profile. A rejection does not move the stream backward; the generator may simply submit a fresh characterization with new lab results.

### 3.2. Reuse Eligibility and State Permitting

Characterization establishes what the material is; eligibility establishes where it may go. A `ComplianceOfficer` files a **reuse-eligibility determination** under a stream, supplying the two-letter `state_code` the determination applies to, the beneficial-reuse `use_case` — one of `CEMENT_ADDITIVE`, `ROAD_BASE`, `SOIL_AMENDMENT`, or `MINE_RECLAMATION` — and a half-open validity window: `valid_from` is the inclusive start date and `valid_until` the exclusive end date, which must be after `valid_from` (a violation is rejected with `ERR_INVALID_REQUEST`). Filing is refused with `ERR_STREAM_NOT_CHARACTERIZED` unless at least one characterization profile of the stream has reached `VERIFIED`. A filed determination starts in `DRAFT`, with the filer's `X-User-ID` stamped as `filed_by_user_id`, while `approved_by_user_id` and `decision_reason` remain null. The determinations of a stream can be listed under it, and reading them applies the lazy expiration of §2.4.

Moving a determination out of `DRAFT` means submitting it for decision. Submission is guarded by two checks: the stream must still have a `VERIFIED` characterization (else `ERR_STREAM_NOT_CHARACTERIZED`), and the half-open window must not overlap the window of any other determination for the same stream and state pair currently in `SUBMITTED`, `APPROVED`, or `SUSPENDED` status (else `ERR_ELIGIBILITY_WINDOW_OVERLAP`). The guards fire in the pipeline order of §2.10 — the window-overlap check (stage 10) before the characterization re-check (stage 12) — so a draft that would fail both draws `ERR_ELIGIBILITY_WINDOW_OVERLAP`. Because windows are half-open, two determinations whose windows merely touch at a boundary date do not overlap.

Adjudication enforces segregation of duties. Approval moves a determination from `SUBMITTED` to `APPROVED` and is only valid when the acting officer's `X-User-ID` differs from the determination's `filed_by_user_id` — an officer approving their own filing is rejected with `ERR_SEGREGATION_OF_DUTIES`. Approval re-runs the window-overlap guard against `SUBMITTED`, `APPROVED`, and `SUSPENDED` peers (else `ERR_ELIGIBILITY_WINDOW_OVERLAP`) and then requires `valid_until` to still be after the current logical date (else `ERR_ELIGIBILITY_WINDOW_PAST`), in that order. On approval, the approver's id is stamped as `approved_by_user_id`, and when the owning stream is still `CHARACTERIZED` it bubbles up to `ACTIVE`, refreshing `updated_at` and incrementing `version`. Denial moves a determination from `SUBMITTED` to `DENIED`; it enforces the same segregation-of-duties rule against the filer and records the payload's `reason` as `decision_reason`.

A denied determination is not dead: revision returns it from `DENIED` to `DRAFT`, clearing both `decision_reason` and `approved_by_user_id` so the officer can rework the window or use case and resubmit through the same pipeline. An approved determination can be suspended, moving from `APPROVED` to `SUSPENDED`, and later reinstated from `SUSPENDED` back to `APPROVED`; reinstatement re-runs the overlap guard against the same peers first (`ERR_ELIGIBILITY_WINDOW_OVERLAP`) and then re-checks that `valid_until` is still in the future (`ERR_ELIGIBILITY_WINDOW_PAST`), leaving `approved_by_user_id` unchanged. Finally, both `APPROVED` and `SUSPENDED` determinations expire lazily into the terminal `EXPIRED` state once the current logical date reaches or passes `valid_until`, as described in §2.4.

Permits run on a parallel track. A `ComplianceOfficer` files a **state permit** for a state and material pair, supplying `state_code`, `material_type` (the same five material classes), the regulatory `regime` — either `PERMIT` or `NOTIFICATION` — the regulator-issued `permit_number`, the ISO issuance date `issued_on`, and `expires_on`, the inclusive last valid day, which must be on or after `issued_on` (a violation is rejected with `ERR_INVALID_REQUEST`). A filed permit starts in `FILED` status. The registry enforces uniqueness per pair: at most one permit with status `FILED` or `ACTIVE` may exist for a given state and material combination, so filing a second such permit — or activating a permit while another `FILED` or `ACTIVE` permit exists for the pair — is rejected with `ERR_DUPLICATE_PERMIT`. Activation moves a permit from `FILED` to `ACTIVE`; revocation moves it from `ACTIVE` to the terminal `REVOKED` state; and an `ACTIVE` permit expires lazily into the terminal `EXPIRED` state once the current logical date passes `expires_on`. The permit registry can be listed with optional `state_code`, `material_type`, and `status` filters, and reads apply the lazy expiration.

### 3.3. Supply Agreements and Offtake Commitments

Commercial booking rests on two-sided commitments. On the sell side, a Generator creates a **supply agreement** whose `generator_id` must equal the acting Generator's own id. The agreement names the covered `stream_id`, caps monthly volume with `committed_monthly_tons`, a positive integer, and fixes the two commercial shares: `revenue_share_pct_to_generator`, the fraction of final gross revenue paid to the generator, which must be strictly greater than 0 and strictly less than 1; and `freight_share_pct_to_generator`, the fraction of freight cost the generator absorbs, which may be anywhere from 0 to 1 inclusive. The agreement's term runs from the inclusive `term_start` date through the inclusive `term_end` date, which must be on or after `term_start`. A new agreement starts in `DRAFT` with both month-to-date counters at zero, `fulfillment_status` of `UNMET`, and `counter_month` stamped with the current logical month.

A `BrokerOps` operator activates a draft agreement, but only when the covered stream has reached `CHARACTERIZED` or `ACTIVE` — activating against an uncharacterized stream is rejected with `ERR_STREAM_NOT_CHARACTERIZED`. Activation stamps the agreement's `counter_month` with the current logical month. From `ACTIVE`, the operator may suspend the agreement into `SUSPENDED` and later resume it back to `ACTIVE`. Termination is available from `DRAFT`, `ACTIVE`, or `SUSPENDED` and moves the agreement to the terminal `TERMINATED` state; any of these actions attempted from a state where it is not declared — including after termination — is rejected with `ERR_INVALID_STATE`. As deliveries accumulate, `fulfillment_status` flips to `MET` whenever `delivered_month_to_date_tons` reaches at least `committed_monthly_tons` within the current counter month, and returns to `UNMET` if the delivered total falls back below the commitment. Agreements can be listed with optional `generator_id`, `stream_id`, and `status` filters, and both list and single-record reads apply the monthly rollover of §2.4 before answering.

On the buy side, an Offtaker creates an **offtake commitment** whose `offtaker_id` must equal the acting Offtaker's own id. The commitment names the covered `stream_id` and the `destination_state_code` of the receiving site — which must appear in the offtaker's own `receiving_state_codes`, else the creation is rejected with `ERR_DESTINATION_NOT_SERVED`. It caps monthly intake with `committed_monthly_tons`, a positive integer that later doubles as the basis of the rejection tolerance (§3.6), and embeds the destination quality specification as `max_moisture_pct` and `max_arsenic_ppm`. A new commitment starts in `DRAFT` with its counters at zero and `counter_month` stamped with the current logical month. Broker-side activation mirrors agreements: the covered stream must be `CHARACTERIZED` or `ACTIVE` (else `ERR_STREAM_NOT_CHARACTERIZED`), and activation stamps `counter_month`. A suspended commitment can be resumed from `SUSPENDED` back to `ACTIVE`, and termination is available from `DRAFT`, `ACTIVE`, or `SUSPENDED` into terminal `TERMINATED`. Note that a commitment has no manual suspend operation — it reaches `SUSPENDED` only automatically, through the rejection-tolerance cascade described in §3.6 — though resumption is always manual. Commitments can be listed with optional `offtaker_id`, `stream_id`, and `status` filters, and reads apply the same lazy monthly rollover.

### 3.4. Booking Loads: Freight, Quotas, and Provisional Pricing

Once an agreement and a commitment both stand `ACTIVE`, the Generator books a **shipment** against the pair. The booking payload carries `supply_agreement_id` and `offtake_commitment_id`, the scheduled `pickup_date`, the one-way haul `distance_miles` as a non-negative integer, the `gross_tons` loaded as a strictly positive number, the `loading_moisture_pct` measured at the loadout, and the optimistic-concurrency field `expected_supply_agreement_version` described in §2.9 — a stale value stops the booking with `ERR_STALE_AGREEMENT_VERSION` before any other business check runs.

The remaining checks fire in the pipeline order of §2.10. The agreement must be `ACTIVE` (else `ERR_AGREEMENT_NOT_ACTIVE`) and the commitment must be `ACTIVE` (else `ERR_COMMITMENT_NOT_ACTIVE`). The scheduled `pickup_date` must fall within the agreement's inclusive term, from `term_start` through `term_end` (else `ERR_OUTSIDE_AGREEMENT_TERM`). The agreement and the commitment must cover the same stream — if the agreement's `stream_id` differs from the commitment's, the booking is rejected with `ERR_STREAM_MISMATCH`. Monthly quotas then bind on both sides, evaluated after any monthly rollover: the agreement's `booked_month_to_date_tons` plus the new `gross_tons` must not exceed the agreement's `committed_monthly_tons`, and the commitment's `accepted_month_to_date_tons` plus the new `gross_tons` must not exceed the commitment's `committed_monthly_tons`; either breach is rejected with `ERR_COMMITMENT_EXCEEDED`. Finally, a market price index entry must be effective for the stream's material in the destination state on `pickup_date`; if none exists, the booking is rejected with `ERR_PRICE_INDEX_GAP`.

A successful booking computes its economics before touching quota. The market price is pinned as `price_at_pickup_cents_per_ton`, selected per the index rules of §3.8 for the stream's `material_type` and the commitment's `destination_state_code` as of `pickup_date`. Freight is priced once, at booking, and never recomputed for the life of the load. The total freight charge, stored as `freight_total_cents`, is the sum of a flat base fee of 15,000 cents and a tiered distance charge over the one-way haul: the first 100 miles are billed at 450 cents per mile, any further miles up to a cumulative 300 miles are billed at 320 cents per mile, and every mile beyond 300 is billed at 210 cents per mile. From that total, the generator absorbs `generator_freight_share_cents`: the freight total multiplied by the agreement's `freight_share_pct_to_generator`, rounded half-up to whole cents, and then capped at 60,000 cents — when the rounded product exceeds the cap, the generator absorbs exactly 60,000 cents. The broker absorbs the remainder, recorded as `broker_freight_share_cents`, which is always the total minus the generator's capped share. Booking also records a provisional settlement estimate: `provisional_settlement_cents` is the `gross_tons` multiplied by `price_at_pickup_cents_per_ton`, rounded half-up to whole cents, using gross tonnage with no moisture adjustment.

The new shipment starts in `BOOKED` status. Its destination measurements (`destination_moisture_pct`, `destination_arsenic_ppm`) and all acceptance-time financial fields — `price_at_acceptance_cents_per_ton`, `moisture_deduction_pct`, `net_billable_tons`, `final_gross_revenue_cents`, `final_generator_share_cents`, `final_broker_share_cents`, `generator_net_payout_cents` — remain null until delivery and acceptance, and `rejection_reason` and `void_reason` remain null unless those outcomes occur. As its quota side effect, booking adds `gross_tons` to the agreement's `booked_month_to_date_tons` (after rollover) and advances the agreement's `version` by one. The shipment ledger can be listed with optional `supply_agreement_id`, `offtake_commitment_id`, and `status` filters.

### 3.5. Dispatch, Delivery, and Acceptance Settlement

Dispatching a booked load is the Generator's act and re-validates the regulatory perimeter at the moment of departure. The load must still be `BOOKED` (else `ERR_INVALID_STATE`), the agreement must be `ACTIVE` (else `ERR_AGREEMENT_NOT_ACTIVE`), and the commitment must be `ACTIVE` (else `ERR_COMMITMENT_NOT_ACTIVE`). An `APPROVED` reuse-eligibility determination must exist for the agreement's stream and the commitment's destination state whose window covers the current logical date — that is, the date falls on or after `valid_from` and strictly before `valid_until`; determinations in `SUSPENDED` or `EXPIRED` do not qualify, and absence of a qualifying determination is rejected with `ERR_REUSE_NOT_ELIGIBLE`. An `ACTIVE` state permit must cover the destination state and the stream's material, with the current logical date on or after its `issued_on` and on or before its `expires_on`, else `ERR_PERMIT_REQUIRED`. And the current logical date must fall within the agreement's inclusive term, else `ERR_OUTSIDE_AGREEMENT_TERM`. A cleared dispatch moves the shipment from `BOOKED` to `DISPATCHED`.

Arrival is the Offtaker's record. Delivering a load moves it from `DISPATCHED` to `DELIVERED` and stamps the spot-check measurements supplied in the payload: `destination_moisture_pct` and `destination_arsenic_ppm`. From there the load stands at the quality gate.

Acceptance decides the money. Accepting a load is declared only from `DELIVERED` (else `ERR_INVALID_STATE`) and first enforces the commitment's quality specification: the destination moisture reading must not exceed the commitment's `max_moisture_pct` by more than 2.0 percentage points, and the destination arsenic reading must not exceed `max_arsenic_ppm` at all; a breach of either limit is rejected with `ERR_QUALITY_OUT_OF_SPEC` and leaves the shipment in `DELIVERED`. A passing load transitions to `ACCEPTED` and runs the final settlement in a pinned evaluation order. First, `moisture_deduction_pct` is the amount by which `destination_moisture_pct` exceeds the commitment's `max_moisture_pct`, or zero when the reading is at or below the limit. Second, `net_billable_tons` is the shipment's `gross_tons` multiplied by one minus that deduction percentage divided by one hundred, rounded half-up to three decimal places. Third, `price_at_acceptance_cents_per_ton` is selected from the market index for the stream's material and destination state as of the acceptance date, exactly as at booking — except that when no index entry is effective on that date, the acceptance price falls back to `price_at_pickup_cents_per_ton` instead of failing. Fourth, `final_gross_revenue_cents` is the rounded `net_billable_tons` — never the unrounded tonnage — multiplied by the acceptance price, rounded half-up to whole cents. Fifth, `final_generator_share_cents` is the gross revenue multiplied by the agreement's `revenue_share_pct_to_generator`, rounded half-up to whole cents. Sixth, `final_broker_share_cents` is the residual, gross revenue minus the generator share, so all rounding drift lands on the broker's side. Seventh, `generator_net_payout_cents` is the generator's revenue share minus the `generator_freight_share_cents` fixed at booking. Because the final variant prices moisture-adjusted tonnage at the acceptance-date index while the provisional variant priced gross tonnage at the pickup-date index, the two figures for the same load diverge whenever the index moved or any moisture deduction applied.

The acceptance cascade then propagates outward. The agreement's `delivered_month_to_date_tons` increases by `net_billable_tons` (after rollover), its `fulfillment_status` is recomputed, and its `version` advances by one; the commitment's `accepted_month_to_date_tons` increases by the same tonnage (after rollover) and its `version` advances by one. A sustainability credit entry is posted with `entry_type` `ACCRUAL`, crediting the agreement's generator, referencing this shipment, posted to the current logical month as its `period`, with `tons_credited` equal to `net_billable_tons` and `credits` equal to those net billable tons multiplied by 1.0 credit per ton, rounded half-up to two decimal places. Posting that entry recomputes the generator's `total_credits` — the sum of `ACCRUAL` credits minus the sum of `REVERSAL` credits across all its entries — and re-derives `credit_tier`: `GOLD` when the balance reaches at least 250, otherwise `SILVER` when it reaches at least 100, otherwise `STANDARD`, with inclusive boundaries so that exactly 100.00 credits already yields `SILVER`.

### 3.6. Rejection, Reconditioning, Disposal, Cancellation, and Voiding

When a delivered load fails the offtaker's review, rejecting it moves the shipment from `DELIVERED` to `REJECTED` (any other source state draws `ERR_INVALID_STATE`) and records the payload's `reason` as the shipment's `rejection_reason`. The rejection then feeds the commitment's tolerance posture: `cumulative_rejected_tons` increases by the shipment's `gross_tons` and the commitment's `version` advances by one. The tolerance threshold itself is the commitment's `committed_monthly_tons` multiplied by 0.20, rounded half-up to three decimal places; if the commitment was `ACTIVE` and, after the current rejection has been added, `cumulative_rejected_tons` strictly exceeds that threshold, the commitment automatically transitions from `ACTIVE` to `SUSPENDED`. A cumulative total exactly equal to the threshold does not suspend.

The auto-suspension is conditional and deliberately scoped. It cancels every shipment of that commitment still in `BOOKED` status, moving each to `CANCELLED`; shipments already `DISPATCHED` or further along are not affected. Each such auto-cancelled shipment releases its quota: its supply agreement's `booked_month_to_date_tons` decreases by that shipment's `gross_tons` (after rollover) and the agreement's `version` advances by one.

A rejected load has three forward paths, all driven by the Generator. Reconditioning moves it from `REJECTED` to `RECONDITIONING`; redelivery then returns it from `RECONDITIONING` to `DELIVERED` with freshly supplied `destination_moisture_pct` and `destination_arsenic_ppm` measurements stamped over the old ones; the earlier `rejection_reason` is retained, and is overwritten only if the load is rejected again. The loop is genuinely cyclic — a redelivered load may be accepted or rejected again, and each rejection adds the full `gross_tons` to `cumulative_rejected_tons` once more. Alternatively, disposal moves a `REJECTED` load to the terminal `DISPOSED` state, closing it out of the reuse stream entirely.

Two unwinds bracket the happy path. A Generator may cancel a load still in `BOOKED` status, moving it to terminal `CANCELLED`; the agreement's `booked_month_to_date_tons` decreases by the shipment's `gross_tons` after rollover, never dropping below zero, and the agreement's `version` advances by one. And a `BrokerOps` operator may void a load already `ACCEPTED`, moving it to terminal `VOIDED` with the payload's `reason` recorded as `void_reason`. Voiding unwinds the full acceptance cascade: a sustainability credit entry of `entry_type` `REVERSAL` is posted for the same generator and shipment, in the current logical `period`, with `tons_credited` equal to the shipment's `net_billable_tons` and `credits` exactly equal to the original `ACCRUAL` credits of that shipment; the generator's `total_credits` is recomputed as the accrual sum minus the reversal sum, and `credit_tier` is re-derived against the same thresholds, which may now downgrade the tier. The agreement's `delivered_month_to_date_tons` decreases by `net_billable_tons` after rollover (floored at zero) with `fulfillment_status` recomputed and `version` advanced, and the commitment's `accepted_month_to_date_tons` decreases the same way, floored at zero, with its `version` advanced.

### 3.7. Buffer Storage and Seasonal Inventory

Production and demand rarely align seasonally, so the broker operates buffer storage. A `BrokerOps` operator registers a **storage facility** with its two-letter `state_code`, the `material_types_allowed` list naming which material classes the facility accepts — each entry must be one of the five material classes, else `ERR_INVALID_REQUEST` — and a strictly positive integer `capacity_tons` ceiling on simultaneous stored tonnage; a new facility's `current_inventory_tons` starts at zero.

Reserving space commits tonnage against that ceiling. A reservation names the `facility_id` and the `stream_id` of the material to be stored, a half-open window from the inclusive `start_date` to the exclusive `end_date` — `end_date` must be after `start_date`, else `ERR_RESERVATION_WINDOW_INVALID` — and a strictly positive `tons` of committed capacity. Two business checks follow in pipeline order: the stream's `material_type` must appear in the facility's `material_types_allowed` (else `ERR_MATERIAL_NOT_ACCEPTED`), and the per-day capacity aggregate must hold (else `ERR_STORAGE_CAPACITY_EXCEEDED`). That aggregate is evaluated day by day: for each calendar day in the new reservation's half-open window that is covered by at least one of the facility's existing reservations in `RESERVED` or `CHECKED_IN` status, the system sums `tons` over the qualifying existing reservations whose own half-open windows contain that day, and the reservation is rejected whenever that sum plus the new `tons` would exceed `capacity_tons`. A day of the new window covered by no existing qualifying reservation is never evaluated, so a reservation that overlaps no existing `RESERVED` or `CHECKED_IN` reservation is admitted regardless of how its `tons` compares to `capacity_tons`. A sum that merely equals capacity is allowed, and adjacency does not count as overlap — one reservation ending on a given day and another starting that same day share no day of coverage.

A new reservation starts in `RESERVED`. Checking material in moves it from `RESERVED` to `CHECKED_IN` and is only permitted within the window — the current logical date must fall on or after `start_date` and strictly before `end_date`, else `ERR_RESERVATION_WINDOW_INVALID`; check-in adds the reservation's `tons` to the facility's `current_inventory_tons` and advances the facility's `version` by one. Releasing moves a reservation from `CHECKED_IN` to terminal `RELEASED`, subtracting its `tons` from `current_inventory_tons` and again advancing the facility's `version`. Cancelling moves a `RESERVED` reservation to terminal `CANCELLED` with no inventory effect. The facility's `current_inventory_tons` is therefore always the sum of `tons` across its `CHECKED_IN` reservations, and reading a facility reports that live figure. Reservations can be listed with optional `facility_id`, `stream_id`, and `status` filters.

### 3.8. Market Pricing and Sustainability Credit Reporting

The market price index is an append-only feed. A `BrokerOps` operator publishes each entry with the priced `material_type`, the two-letter `region_code` the price applies to, the ISO `effective_from` date on which the price becomes effective, and `price_cents_per_ton` as a strictly positive integer number of cents; the publisher's `X-User-ID` is stamped as `published_by_user_id`. Entries are never modified or deleted after publication, and the feed can be listed with optional `material_type` and `region_code` filters.

One selection rule serves both booking and acceptance. The candidate set is every index entry whose `material_type` matches the stream's material and whose `region_code` equals the commitment's `destination_state_code`, restricted to entries whose `effective_from` falls on or before the pricing date; dates compare at day granularity against the logical clock. The winner is the candidate with the latest `effective_from`, with ties broken in favor of the most recently created entry. At booking, an empty candidate set is fatal — `ERR_PRICE_INDEX_GAP`; at acceptance, an empty set instead falls back to the shipment's `price_at_pickup_cents_per_ton`, so settlement can never stall on a publishing gap.

Sustainability credits are the reporting layer over accepted diversion. **Credit entries** are created only by the acceptance and voiding cascades — never directly — and each records the credited `generator_id`, the originating `shipment_id`, an `entry_type` of `ACCRUAL` or `REVERSAL`, the YYYY-MM `period` of posting, the `tons_credited` the entry is based on, and the credit `credits` amount itself. The amount is a positive number on both row types; the sign is carried by `entry_type`. Entries are listed per shipment or per generator, and a generator's record always exposes the live `total_credits` balance and derived `credit_tier`.

Two reporting variants coexist. The **standard** variant is the ledger view: for a given period, `standard_credits` is the signed sum of that period's entries — accrual amounts added, reversal amounts subtracted — so a voided shipment offsets its own accrual. The **attested** variant, produced for regulatory reporting, is instead computed directly from shipments: it considers the generator's loads that remain in `ACCEPTED` status and were accepted during the period — voided shipments are excluded entirely rather than offset — sums their `net_billable_tons` (reported as `total_net_tons`), multiplies the total by 0.92, and rounds half-up to two decimal places to produce `attested_credits`. An identical diversion history therefore always yields an attested figure at or below the standard one. A computed read endpoint returns both variants for a generator, accepting an optional `period` query parameter in YYYY-MM form that defaults to the current logical month when omitted or empty and is not otherwise format-validated — a period matching no entries simply yields zeroes — and responding with `standard_credits`, `attested_credits`, `total_net_tons`, and the generator's current `credit_tier`.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code, while operations that act on or modify an existing resource return `200 OK`. All endpoints are mounted under the `/api` prefix and authenticated per §2.1; the table below summarizes each operation, and the full request and response semantics are defined by the narratives of §2 and §3.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/generators` | Register a generator organization | BrokerOps |
| GET | `/api/generators` | List generators | All roles |
| GET | `/api/generators/{id}` | Read one generator, including `total_credits` and `credit_tier` | All roles |
| POST | `/api/offtakers` | Register an offtaker organization | BrokerOps |
| GET | `/api/offtakers` | List offtakers | All roles |
| POST | `/api/streams` | Register a byproduct stream | Generator |
| GET | `/api/streams` | List streams, filterable | All roles |
| GET | `/api/streams/{id}` | Read one stream | All roles |
| POST | `/api/streams/{id}/characterizations` | Submit a lab characterization for a stream | Generator |
| GET | `/api/streams/{id}/characterizations` | List characterizations of a stream | All roles |
| POST | `/api/characterizations/{id}/verify` | Verify a submitted characterization | BrokerOps |
| POST | `/api/characterizations/{id}/reject` | Reject a submitted characterization | BrokerOps |
| POST | `/api/streams/{id}/eligibility-determinations` | File a draft reuse-eligibility determination | ComplianceOfficer |
| GET | `/api/streams/{id}/eligibility-determinations` | List eligibility determinations of a stream | All roles |
| POST | `/api/eligibility-determinations/{id}/submit` | Submit a draft determination for decision | ComplianceOfficer |
| POST | `/api/eligibility-determinations/{id}/revise` | Reopen a denied determination to draft | ComplianceOfficer |
| POST | `/api/eligibility-determinations/{id}/approve` | Approve a submitted determination | ComplianceOfficer |
| POST | `/api/eligibility-determinations/{id}/deny` | Deny a submitted determination | ComplianceOfficer |
| POST | `/api/eligibility-determinations/{id}/suspend` | Suspend an approved determination | ComplianceOfficer |
| POST | `/api/eligibility-determinations/{id}/reinstate` | Reinstate a suspended determination | ComplianceOfficer |
| POST | `/api/state-permits` | File a state permit or notification | ComplianceOfficer |
| GET | `/api/state-permits` | List state permits, filterable | All roles |
| POST | `/api/state-permits/{id}/activate` | Activate a filed permit | ComplianceOfficer |
| POST | `/api/state-permits/{id}/revoke` | Revoke an active permit | ComplianceOfficer |
| POST | `/api/supply-agreements` | Create a supply agreement | Generator |
| GET | `/api/supply-agreements` | List supply agreements, filterable | All roles |
| GET | `/api/supply-agreements/{id}` | Read one supply agreement | All roles |
| POST | `/api/supply-agreements/{id}/activate` | Activate a draft agreement | BrokerOps |
| POST | `/api/supply-agreements/{id}/suspend` | Suspend an active agreement | BrokerOps |
| POST | `/api/supply-agreements/{id}/resume` | Resume a suspended agreement | BrokerOps |
| POST | `/api/supply-agreements/{id}/terminate` | Terminate an agreement | BrokerOps |
| POST | `/api/offtake-commitments` | Create an offtake commitment with quality spec | Offtaker |
| GET | `/api/offtake-commitments` | List offtake commitments, filterable | All roles |
| GET | `/api/offtake-commitments/{id}` | Read one offtake commitment | All roles |
| POST | `/api/offtake-commitments/{id}/activate` | Activate a draft commitment | BrokerOps |
| POST | `/api/offtake-commitments/{id}/resume` | Resume a suspended commitment | BrokerOps |
| POST | `/api/offtake-commitments/{id}/terminate` | Terminate a commitment | BrokerOps |
| POST | `/api/shipments` | Book a load against an agreement and commitment | Generator |
| GET | `/api/shipments` | List shipments, filterable | All roles |
| GET | `/api/shipments/{id}` | Read one shipment | All roles |
| POST | `/api/shipments/{id}/dispatch` | Dispatch a booked load | Generator |
| POST | `/api/shipments/{id}/deliver` | Record destination arrival and spot-check measurements | Offtaker |
| POST | `/api/shipments/{id}/accept` | Accept a delivered load and settle | Offtaker |
| POST | `/api/shipments/{id}/reject` | Reject a delivered load | Offtaker |
| POST | `/api/shipments/{id}/recondition` | Send a rejected load to reconditioning | Generator |
| POST | `/api/shipments/{id}/redeliver` | Redeliver a reconditioned load with fresh measurements | Generator |
| POST | `/api/shipments/{id}/dispose` | Dispose of a rejected load | Generator |
| POST | `/api/shipments/{id}/cancel` | Cancel a booked load | Generator |
| POST | `/api/shipments/{id}/void` | Void an accepted load and unwind settlement | BrokerOps |
| GET | `/api/shipments/{id}/credit-entries` | List credit entries of a shipment | All roles |
| POST | `/api/storage-facilities` | Register a buffer-storage facility | BrokerOps |
| GET | `/api/storage-facilities/{id}` | Read one facility, including live inventory | All roles |
| POST | `/api/storage-reservations` | Reserve storage capacity for a half-open window | BrokerOps |
| GET | `/api/storage-reservations` | List storage reservations, filterable | All roles |
| GET | `/api/storage-reservations/{id}` | Read one storage reservation | All roles |
| POST | `/api/storage-reservations/{id}/check-in` | Check material into storage within the window | BrokerOps |
| POST | `/api/storage-reservations/{id}/release` | Release checked-in material | BrokerOps |
| POST | `/api/storage-reservations/{id}/cancel` | Cancel a reserved reservation | BrokerOps |
| POST | `/api/price-index-entries` | Publish an append-only market price index entry | BrokerOps |
| GET | `/api/price-index-entries` | List price index entries, filterable | All roles |
| GET | `/api/generators/{id}/credit-entries` | List credit entries of a generator | All roles |
| GET | `/api/generators/{id}/credit-summary` | Read standard versus attested credit variants for a period | All roles |
| POST | `/api/_clock/set_current_utc` | Set the logical clock | PlatformAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are defined where the guarded workflow is described in §2 and §3; the catalogue below is the enumeration of identifiers and statuses only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN` | 403 Forbidden |
| `ERR_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_FK_NOT_FOUND` | 422 Unprocessable Entity |
| `ERR_STALE_AGREEMENT_VERSION` | 412 Precondition Failed |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_AGREEMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_COMMITMENT_NOT_ACTIVE` | 409 Conflict |
| `ERR_REUSE_NOT_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_PERMIT_REQUIRED` | 422 Unprocessable Entity |
| `ERR_OUTSIDE_AGREEMENT_TERM` | 422 Unprocessable Entity |
| `ERR_ELIGIBILITY_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_ELIGIBILITY_WINDOW_PAST` | 422 Unprocessable Entity |
| `ERR_RESERVATION_WINDOW_INVALID` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_PERMIT` | 409 Conflict |
| `ERR_MATERIAL_NOT_ACCEPTED` | 422 Unprocessable Entity |
| `ERR_STORAGE_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_QUALITY_OUT_OF_SPEC` | 422 Unprocessable Entity |
| `ERR_STREAM_NOT_CHARACTERIZED` | 422 Unprocessable Entity |
| `ERR_DESTINATION_NOT_SERVED` | 422 Unprocessable Entity |
| `ERR_STREAM_MISMATCH` | 422 Unprocessable Entity |
| `ERR_COMMITMENT_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_PRICE_INDEX_GAP` | 422 Unprocessable Entity |
