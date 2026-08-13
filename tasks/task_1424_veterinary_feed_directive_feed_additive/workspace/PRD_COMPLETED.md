# Veterinary Feed Directive Feed Mill API — Product Requirements Document

## 1. Introduction

The Veterinary Feed Directive (VFD) framework under 21 CFR 558 requires that certain medically important antimicrobials administered through animal feed be used only under the written authorization of a licensed veterinarian operating within a valid veterinarian-client-patient relationship. Feed mills sit at the operational chokepoint of this regime: they must refuse to manufacture or ship medicated feed unless the paperwork is sound, they must keep distributor acknowledgment letters on file, and they must be able to produce records for inspection on demand. Producers, meanwhile, carry the obligation to observe the labeled withdrawal period before sending animals to market, and inspectors carry the obligation to chase residue violations back to the issuing clinic when meat tests positive.

This document specifies an API that acts as the shared operational registry for a feed-mill VFD compliance program. It records clinics, veterinarians, producers, animal groups, and VFD drugs; tracks the lifecycle of a VFD authorization from issuance through partial or full use, expiration, revocation, or supersession; gates each feed order through validation against its VFD before it can ship; projects withdrawal windows both provisionally at validation time and definitively at delivery; and opens residue cases when a withdrawal plan is violated. An audit bundle mechanism closes the loop by letting an inspector demand a producer's records for a defined lookback window and marking the producer deficient — with automatic suspension — when those records do not materialize.

The system is read by four constituencies with deliberately segregated duties: inspectors onboard and discipline the parties, veterinarians issue and revoke authorizations, feed-mill operators validate and ship feed, and producers attest to delivery and last-feed timing. No single role can both authorize feed and fulfill it, and no single role can both run an audit and produce the records the audit demands.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers. `X-User-ID` identifies the acting user; `X-User-Role` declares the role under which that user is acting. Four role strings are recognized, with exact spelling: `Inspector`, `Veterinarian`, `FeedMillOperator`, and `Producer`. A request whose `X-User-Role` header is missing, malformed, or not one of these four values is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is recognized but not permitted for the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The four roles differ in how `X-User-ID` binds to persisted entities. When `X-User-Role` is `Veterinarian`, `X-User-ID` is the `id` of the acting `Veterinarian`; ownership checks on any resource that references a `Veterinarian` (for example a `VfdAuthorization` or a `VcpVerification`) compare the resource's `vet_id` field to `X-User-ID`. When `X-User-Role` is `FeedMillOperator`, `X-User-ID` is the `id` of the acting `FeedMill`; ownership checks on any resource that references a `FeedMill` compare the resource's `feed_mill_id` to `X-User-ID`. When `X-User-Role` is `Producer`, `X-User-ID` is the `id` of the acting `Producer`; ownership checks on any resource that references a `Producer` compare the resource's `producer_id` to `X-User-ID`. When `X-User-Role` is `Inspector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example as `investigator_id` on a `ResidueCase`) but does not compare it against any entity's `id`.

A third auth check fires when an endpoint requires entity-backed identity and the acting user's `X-User-ID` does not match the resource's owning foreign key. Recording a VCPR or issuing a VFD requires `X-User-ID` to equal the payload's `vet_id`; submitting a feed order requires `X-User-ID` to equal the path feed mill's `id`; validating, rejecting, or shipping a feed order requires `X-User-ID` to equal the order's `feed_mill_id`; revoking a VFD requires the caller to be the same veterinarian who issued it; cancelling a feed order as a `Producer` requires the caller to be the producer named on the order; confirming delivery, returning a shipment, or rejecting receipt all require the caller to be the order's producer; marking an audit record produced requires the caller to be the bundle's producer; and revoking a VCPR requires the caller to be the veterinarian named on that VCPR. Any mismatch on one of these checks is rejected with `ERR_FORBIDDEN` (HTTP 403). Only the `X-User-Role` header is validated for authentication: a missing `X-User-ID` is not itself an authentication failure, but it matches no entity and therefore fails every one of these ownership checks.

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

Missing required fields, non-integer values for integer fields, malformed JSON bodies, unparseable timestamps, and invalid enum values are all rejected with `ERR_INVALID_REQUEST` (HTTP 400). A request to an unrecognized path is rejected with `ERR_NOT_FOUND` (HTTP 404); a recognized path addressed with an unsupported method is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 2.3. Pagination

List endpoints accept two query parameters. `limit` controls the page size and defaults to 10; it must be at least 1 and may not exceed 100. `offset` controls how many records are skipped before the page begins and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the range 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). List responses are always sorted by `created_at` ascending, with ties broken by `id` ascending. The `meta` block of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`, where `has_more` is true exactly when `offset` plus the number of records returned is less than `total_count`.

### 2.4. Resource Identity and Mutation Metadata

Every persisted resource carries an `id` assigned by the server as a UUID with no type prefix, a `created_at` timestamp in ISO 8601 UTC with three fractional digits, an `updated_at` timestamp in the same format that refreshes on every mutation, and a `version` integer that starts at 1 and increments on every mutation. Some entities in this domain are append-only and do not participate in optimistic concurrency; where an entity is described in §3 as being created once and never subsequently mutated, its `updated_at` and `version` are still present and behave as just described. A field that has never been assigned a value is omitted from the response; a field explicitly assigned null (for example `residue_ppb`, `tolerance_ppb`, `investigator_id`, or `severity_tier` on an unresolved `ResidueCase`) is serialized with an explicit null rather than omitted.

Referenced identifiers are validated left-to-right: the path's identifiers are checked first, then the body's, and the first missing reference yields `ERR_NOT_FOUND` (HTTP 404). Within the body, required-field presence and type checks fire before the existence of body-referenced identifiers is verified.

### 2.5. Logical Clock and Time-Driven Transitions

The system maintains a logical clock rather than reading wall-clock time. At server startup the clock reads `2026-08-01T00:00:00Z`. An inspector may advance it by supplying a target `to_iso8601` timestamp through the clock endpoint; the response echoes the current time as `now_utc`. The endpoint accepts any parseable target timestamp, including one earlier than the current logical time — no monotonicity check is applied. Advancing the clock re-evaluates two families of time-driven state transitions: any `VfdAuthorization` currently in `ISSUED` or `PARTIALLY_USED` whose `expiration_date` has been reached or passed (logical time greater than or equal to `expiration_date`) transitions to `EXPIRED`, and any `VcpVerification` currently in `ACTIVE` whose `expires_on` has been reached or passed transitions to `EXPIRED`. Both transitions fire the cascades described in §3.

### 2.6. Withdrawal-Window Precision

All withdrawal projections are expressed in whole-minute UTC precision. Whenever a calculation produces a timestamp, the result is truncated to the whole minute — never rounded up. This rule applies identically to the provisional projection computed at feed-order validation time and to the final projection computed at shipment delivery time.

### 2.7. Optimistic Concurrency on the VFD Authorization

Two write operations carry an optimistic-concurrency guard against a `VfdAuthorization`. Both take a required `expected_vfd_authorization_version` field carrying the version of the VFD the caller last observed. Issuing a replacement VFD via the `supersedes_id` parameter is one such operation: if the existing VFD's current `version` no longer matches `expected_vfd_authorization_version`, the issuance is rejected with `ERR_STALE_VERSION` (HTTP 412), because another writer has already superseded or otherwise mutated the same VFD. Validating a feed order is the other: the validation request must carry `expected_vfd_authorization_version` matching the VFD's current `version`, and a mismatch — which signals that another order validation has just debited the VFD's `remaining_animal_count` — is likewise rejected with `ERR_STALE_VERSION` (HTTP 412). Endpoints not named here do not accept a version field.

### 2.8. Quota Accounting on the VFD

Each `VfdAuthorization` carries an authorized head-count pool. Its `remaining_animal_count` is derived as `authorized_animal_count` minus the sum of `animal_count` across every `FeedOrder` bound to this VFD whose status is `VALIDATED`, `SHIPPED`, or `DELIVERED`. The deduction happens when an order transitions into `VALIDATED`. A compensating return happens when an order leaves `VALIDATED` for `CANCELLED` — whether by explicit cancellation, by a shipment being returned, by a shipment being rejected at receipt, or by a VFD-driven cascade — at which point the order's `animal_count` is added back into `remaining_animal_count` and the VFD's `version` is incremented. A supersede event also zeroes the old VFD's `remaining_animal_count` regardless of what the formula above would produce. Within a VFD-driven cascade, the compensating returns of all cancelled validated orders are applied together as a single recomputation of `remaining_animal_count` from the formula above, and the VFD's `version` increments once for the cascade as a whole rather than once per cancelled order. A return- or rejection-driven compensation adds the order's `animal_count` back to whatever `remaining_animal_count` currently is — even when the VFD is already in a terminal state, for example after a supersede has zeroed it.

### 2.9. Compliance Score and Audit Readiness

Every `VeterinaryClinic` carries a `compliance_score` initialized to 1000 at registration, and a derived `audit_ready` boolean. The score decreases when a residue case traced back to that clinic's veterinarians is confirmed; the precise penalty schedule lives in §3.8. The clinic's `audit_ready` flag is true exactly when two conditions hold simultaneously: the clinic's `compliance_score` is at least 700, and no `ResidueCase` in status `OPEN` exists on any producer reached through any VFD issued by any veterinarian of that clinic. The flag is re-evaluated whenever a `ResidueCase` is opened (by an inspector or automatically at delivery), dismissed, or confirmed: it flips to false the moment either condition fails, and it returns to true as soon as both conditions hold again — although in practice a clinic whose `compliance_score` has dropped below 700 stays unready, because no operation restores the score.

### 2.10. Audit Window Semantics

An `AuditBundle` defines a lookback window from `window_start` to `window_end` using half-open semantics on the window: a record contributes to `required_record_count` only if its `created_at` is strictly before `window_end` and either it has never reached a terminal state or its terminal timestamp is greater than or equal to `window_start`. Records whose terminal timestamp is absent are treated as still alive at audit time. A record created exactly at `window_end` does not count toward the audit; a record that terminated exactly at `window_start` does count. A record's terminal timestamp is the `updated_at` at which it entered a terminal status; the terminal statuses are `EXPIRED`, `REVOKED`, `SUPERSEDED`, and `FULLY_USED` for a `VfdAuthorization`; `DELIVERED`, `CANCELLED`, and `REJECTED` for a `FeedOrder`; `DELIVERED`, `RETURNED`, and `REJECTED_AT_RECEIPT` for a `FeedShipment`; and `LAPSED` for a `DistributorAcknowledgment`. The populations counted are described in §3.9.

## 3. Business Logic & Workflows

### 3.1. Onboarding Clinics, Veterinarians, Producers, Feed Mills, and Drugs

An `Inspector` begins by registering the regulated parties. A `VeterinaryClinic` is registered with its legal `name`, its state-issued `license_number`, and its two-letter `state_code`; a duplicate `license_number` is rejected with `ERR_DUPLICATE_CLINIC_LICENSE` (HTTP 409). At registration the clinic's `compliance_score` is set to 1000 and its `audit_ready` flag to true. A `Veterinarian` is then registered under a clinic with the veterinarian's `full_name`, individual DVM `license_number`, and `state_code`; the veterinarian starts in `ACTIVE` status, and the system records the owning clinic's identifier as the veterinarian's `clinic_id`. A `Producer` is registered with its business `legal_name`, its federal `premise_id`, and its `state_code`; a duplicate `premise_id` is rejected with `ERR_DUPLICATE_PREMISE` (HTTP 409), and the producer starts in `ACTIVE` status. A `FeedMill` is registered with its legal `name`, its `fda_registration` number, and its `state_code`; a duplicate `fda_registration` is rejected with `ERR_DUPLICATE_FDA_REG` (HTTP 409), and the mill's `pending_order_count` initializes to zero.

Once a producer exists, either the producer or an inspector may register an `AnimalGroup` beneath it — when the caller is a `Producer`, no ownership check binds `X-User-ID` to the path producer — supplying `species` (one of `CATTLE`, `SWINE`, `POULTRY`, `SHEEP`, or `GOAT`), `production_class` (one of `BEEF`, `DAIRY`, `LAYER`, `BROILER`, or `BREEDING`), the current `head_count`, the `average_weight_lbs`, and the `earliest_market_date` the producer anticipates for slaughter. Independently, an inspector registers each `VfdDrug` with its FDA `drug_code`, its proprietary `label_name`, the required `withdrawal_hours` before slaughter, the list of label-permitted combinations in `allowed_species_classes` (each entry a string of the form `SPECIES:CLASS`, for example `CATTLE:BEEF`), and the label's `max_duration_days` of continuous feeding. A duplicate `drug_code` is rejected with `ERR_DUPLICATE_DRUG_CODE` (HTTP 409). Every VFD drug's `prohibited_extra_label` flag is pinned to true at registration and cannot be unset — extra-label use of a VFD drug is always prohibited under 21 CFR 530.

### 3.2. Establishing and Revoking the Veterinarian-Client-Patient Relationship

Before any VFD can be issued, the veterinarian must document a valid relationship with the producer. A `Veterinarian` records a `VcpVerification` by supplying the `vet_id` of the veterinarian, the `producer_id` of the subject producer, and an `expires_on` timestamp (typically twelve months out). The recording veterinarian must be `ACTIVE`, otherwise the request is rejected with `ERR_VET_INACTIVE` (HTTP 409). At recording time `verified_on` is set to the current logical time and `status` becomes `ACTIVE`. VCPRs can be listed with optional filters on `vet_id`, `producer_id`, and `status`, alongside `limit` and `offset`.

A VCPR ends in one of two ways. When the logical clock reaches `expires_on`, the VCPR transitions automatically from `ACTIVE` to `EXPIRED` with no further side effects. Alternatively, the veterinarian who owns it may revoke it by supplying a `revocation_reason`, which is recorded on the VCPR; the request is rejected with `ERR_FORBIDDEN` if `X-User-ID` does not match the VCPR's `vet_id`, with `ERR_INVALID_STATE` if the VCPR is not currently `ACTIVE`, and with `ERR_INVALID_REQUEST` if `revocation_reason` is missing. Revoking a VCPR cascades: every `VfdAuthorization` in `ISSUED` or `PARTIALLY_USED` status that was issued by this veterinarian for this producer transitions to `EXPIRED`, and the per-VFD side effects described in §3.4 fire for each one.

### 3.3. Issuing and Superseding a VFD Authorization

A `Veterinarian` issues a `VfdAuthorization` against a producer's animal group. The payload carries `producer_id`, `animal_group_id`, `vet_id`, `drug_id`, the total `authorized_animal_count`, the per-animal `feed_duration_days`, and the `expiration_date`. At issuance the `issued_on` timestamp is set to the current logical time, `status` becomes `ISSUED`, and `remaining_animal_count` is initialized equal to `authorized_animal_count`. The producer must currently be `ACTIVE`; otherwise the issuance is rejected with `ERR_PRODUCER_SUSPENDED` (HTTP 409). The veterinarian must be `ACTIVE`; otherwise the rejection is `ERR_VET_INACTIVE` (HTTP 409). The `expiration_date` may not be more than six calendar months past `issued_on` per 21 CFR 558.6 — computed by adding six to the month of `issued_on`, clamping the day to the last valid day of the resulting month, and preserving the time of day; a strictly longer horizon is rejected with `ERR_VFD_DURATION_EXCEEDED` (HTTP 422), while an `expiration_date` exactly six calendar months out is accepted. An `ACTIVE` VCPR must cover the pair of this veterinarian and this producer at issuance time, otherwise the issuance is rejected with `ERR_VCPR_NOT_VERIFIED` (HTTP 422). The drug's `allowed_species_classes` must contain the `SPECIES:CLASS` pair formed from the target animal group's `species` and `production_class`, otherwise the issuance is rejected with `ERR_SPECIES_CLASS_MISMATCH` (HTTP 422). Finally, the optional `extra_label_intended` flag defaults to false; if a veterinarian attempts to set it to true the issuance is rejected with `ERR_EXTRA_LABEL_USE` (HTTP 422), because VFD drugs admit no extra-label use. The caller's identity is verified after the referenced entities are loaded and before these business checks: `X-User-ID` must equal the payload's `vet_id`, otherwise `ERR_FORBIDDEN`. When several violations are present at once, the business checks are evaluated in the order — extra-label guard, species/class pair, VCPR coverage, six-month duration, producer status, veterinarian status — and earlier failures mask later ones.

A veterinarian may issue a replacement VFD that supersedes an existing one by including `supersedes_id` pointing at the older VFD. The older VFD must currently be in `ISSUED` or `PARTIALLY_USED`. Because supersession is one of the two OCC-guarded writes, the payload must also carry `expected_vfd_authorization_version` matching the older VFD's current `version`; a stale value is rejected with `ERR_STALE_VERSION` (HTTP 412). These supersede checks run only after all of the issuance checks above have passed, in the order: the old VFD's state, then the presence and integer type of `expected_vfd_authorization_version` (otherwise `ERR_INVALID_REQUEST`, HTTP 400), and finally the version comparison. When the supersede succeeds, the older VFD transitions to `SUPERSEDED`, its `version` increments, its `remaining_animal_count` is zeroed, and its `superseded_by_id` is set to the new VFD's `id`. The new VFD is created in `ISSUED` with its own independent `authorized_animal_count`; the new document does not inherit any remainder from the old. Supersession fires the same feed-order cancellation cascade described in §3.4 on the old VFD: every `FeedOrder` bound to the old VFD that is currently in `SUBMITTED` or `VALIDATED` transitions to `CANCELLED` with its `rejection_reason` set to the string `VFD_EXPIRED`, the owning mill's `pending_order_count` is decremented once for each such order that was in `VALIDATED` when it was cancelled, and the `WithdrawalPlan` of any cancelled validated order is left behind in `PROVISIONAL` status as an orphaned record kept for audit. Cancelled orders remain bound to the old VFD; orders that have already advanced past `VALIDATED` (for example `SHIPPED` or `DELIVERED`) are unaffected by the supersede.

VFDs may be listed with filters on `producer_id`, `vet_id`, `drug_id`, `animal_group_id`, `superseded_by_id`, and `status`, or retrieved as a sub-resource of a producer with a `status` filter.

### 3.4. Expiration and Revocation of a VFD, and the Feed-Order Cascade

A `VfdAuthorization` leaves its usable life in three ways, all of which share a common cancellation cascade. The VFD can expire when the logical clock reaches its `expiration_date`; it can be revoked by the veterinarian who issued it, which requires `X-User-ID` to equal the VFD's `vet_id` (otherwise `ERR_FORBIDDEN`) and requires current status `ISSUED` or `PARTIALLY_USED` (otherwise `ERR_INVALID_STATE`); or it can be cascaded into `EXPIRED` when the issuing veterinarian is suspended or revoked, or when the underlying VCPR is revoked. In every case, the transition out of `ISSUED` or `PARTIALLY_USED` into `EXPIRED` (or `REVOKED`) fires the same cascade: every `FeedOrder` for this VFD currently in `SUBMITTED` or `VALIDATED` transitions to `CANCELLED` with its `rejection_reason` set to the string `VFD_EXPIRED`; the owning `FeedMill`'s `pending_order_count` is decremented once for each order that was in `VALIDATED` when it was cancelled; and any order that was in `VALIDATED` leaves its `WithdrawalPlan` behind in `PROVISIONAL` status as an orphaned record kept for audit. The compensating quota return described in §2.8 also fires for each cancelled validated order.

Suspension and revocation of the veterinarian are inspector actions. Suspending a veterinarian who is currently `ACTIVE` moves the veterinarian to `SUSPENDED` (any other starting state is rejected with `ERR_INVALID_STATE`) and fires the cascade above across every `VfdAuthorization` in `ISSUED` or `PARTIALLY_USED` issued by that veterinarian. Reinstating a veterinarian requires current status `SUSPENDED` (any other starting state is rejected with `ERR_INVALID_STATE`) and returns them to `ACTIVE` but does not resurrect any expired VFDs — the veterinarian must re-issue new authorizations. Revoking a veterinarian from either `ACTIVE` or `SUSPENDED` moves them to `REVOKED` and fires the same VFD cascade.

### 3.5. Submitting, Validating, and Rejecting a Feed Order

A `FeedMillOperator` initiates a feed order against a feed mill by supplying `vfd_authorization_id`, `producer_id`, `animal_count`, `tons_of_feed`, and a free-text `intended_use_label` describing how the feed will be used. The order is created in `SUBMITTED` status. The `producer_id` on the order must match the `producer_id` on the referenced VFD (otherwise `ERR_INVALID_REQUEST`, HTTP 400), and the producer must be `ACTIVE` at submission (otherwise `ERR_PRODUCER_SUSPENDED`). The `intended_use_label` must match the label indications of the VFD's drug: the drug's labeled identity for this check is its `label_name`, and the `intended_use_label` matches when the drug's `label_name` appears as a case-sensitive substring within the submitted `intended_use_label` text; a mismatch is an attempted extra-label use and the submission is rejected with `ERR_EXTRA_LABEL_USE` (HTTP 422). The same `ERR_EXTRA_LABEL_USE` guard applies at issuance and at validation — the check is enforced at all three points.

Validation is the gate at which the mill confirms the order is lawful to manufacture. The validation request must carry `expected_vfd_authorization_version` per §2.7. The validation itself enforces eight checks, evaluated in the following priority order so that earlier failures mask later ones. First, the VFD's status must be `ISSUED` or `PARTIALLY_USED` (otherwise `ERR_VFD_NOT_USABLE`, HTTP 409). Second, the logical clock must be strictly before the VFD's `expiration_date` (otherwise `ERR_VFD_EXPIRED`, HTTP 409). Third, the producer must be `ACTIVE` (otherwise `ERR_PRODUCER_SUSPENDED`). Fourth, the order's `animal_count` must not exceed the VFD's current `remaining_animal_count` (otherwise `ERR_VFD_QUOTA_EXCEEDED`, HTTP 409). Fifth, the drug's `allowed_species_classes` must contain the `SPECIES:CLASS` pair of the order's animal group (otherwise `ERR_SPECIES_CLASS_MISMATCH`). Sixth, the `intended_use_label` must match the drug label (otherwise `ERR_EXTRA_LABEL_USE`). Seventh, no `ResidueCase` in `OPEN` status may exist on the same producer (otherwise `ERR_RESIDUE_CASE_OPEN`, HTTP 422). Eighth, an `ACTIVE` VCPR must cover the pair of the VFD's veterinarian and the VFD's producer at validation time (otherwise `ERR_VCPR_NOT_VERIFIED`). These eight checks run only after the caller's identity has been verified against the order's `feed_mill_id` (otherwise `ERR_FORBIDDEN`), after `expected_vfd_authorization_version` has been checked for presence and integer type (otherwise `ERR_INVALID_REQUEST`, HTTP 400), and after the order's state has been confirmed to be `SUBMITTED` (otherwise `ERR_INVALID_STATE`); the optimistic-concurrency comparison of `expected_vfd_authorization_version` against the VFD's current `version` is evaluated only after all eight checks pass.

When validation succeeds, several effects fire together. The order transitions from `SUBMITTED` to `VALIDATED`. A `WithdrawalPlan` is created in `PROVISIONAL` status with `withdrawal_window_hours` copied from the linked drug's `withdrawal_hours` at this moment. The plan's `provisional_market_date` is computed forward-looking: take the current logical time, add the `withdrawal_window_hours`, and compare the result to the animal group's `earliest_market_date`; the provisional market date is whichever of the two is later, truncated to whole-minute UTC. The VFD's `remaining_animal_count` is decremented by the order's `animal_count` and its `version` is incremented; if the VFD was in `ISSUED`, it transitions to `PARTIALLY_USED` on this first validation, and if `remaining_animal_count` reaches zero it transitions to `FULLY_USED` (including directly from `ISSUED` when a single order consumes the entire pool). The quota debit and any resulting status transition are separate mutations, so the VFD's `version` increments once for the debit and once more when the debit also changes the status. The mill's `pending_order_count` increments by one.

A mill may instead reject an order that is still in `SUBMITTED` by supplying a `rejection_reason`; the order transitions to `REJECTED` with the reason recorded. An order in any other state is rejected with `ERR_INVALID_STATE`; a `SUBMITTED` order whose request omits `rejection_reason` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

### 3.6. Shipping, Delivery, and the Withdrawal Plan

Once an order is `VALIDATED`, the mill may ship it by supplying `tons_shipped`. Shipping requires the order to currently be `VALIDATED` (otherwise `ERR_INVALID_STATE`); it requires the logical clock to still be before the VFD's `expiration_date` (otherwise `ERR_VFD_EXPIRED`); and it requires a `DistributorAcknowledgment` in `ACKNOWLEDGED` status to exist covering this mill and this VFD's drug (otherwise `ERR_ACK_MISSING`, HTTP 422). These gating checks are evaluated in the order stated — state, then expiration, then acknowledgment — before the `tons_shipped` payload is validated. On success, the order transitions from `VALIDATED` to `SHIPPED` and a `FeedShipment` is created in `IN_TRANSIT` status with `shipped_at` set to the current logical time.

Delivery, return, and receipt-rejection are producer actions on the shipment. Each requires the shipment to be `IN_TRANSIT` (otherwise `ERR_INVALID_STATE`) and requires `X-User-ID` to equal the order's `producer_id` (otherwise `ERR_FORBIDDEN`). Confirming delivery requires the producer to supply `last_feed_consumed_at`, the attested timestamp when the animals last consumed the medicated feed. On delivery the shipment transitions to `DELIVERED`, `delivered_at` is set to the current logical time, the parent order transitions from `SHIPPED` to `DELIVERED`, the mill's `pending_order_count` decrements by one, and the linked `WithdrawalPlan` is finalized by the chronological variant of the calculation: the plan's `final_market_date` is the attested `last_feed_consumed_at` plus the `withdrawal_window_hours`, truncated to whole-minute UTC. Because it uses the attested last-feed timestamp rather than the validation-time clock, this final value can differ from `provisional_market_date` by days. If the resulting `final_market_date` is on or before the animal group's `earliest_market_date`, the plan transitions from `PROVISIONAL` to `FINALIZED`. If the `final_market_date` falls after the `earliest_market_date`, the plan transitions from `PROVISIONAL` to `VIOLATED` and the delivery is still allowed to complete; the violation is surfaced by automatically opening a `ResidueCase` on the producer with `status` set to `OPEN`, `detected_at` set to the current logical time, and `residue_ppb` left null pending laboratory results (`tolerance_ppb`, `investigator_id`, and `severity_tier` are likewise null, and `penalty_score_deduction` is zero).

A producer may instead return the shipment while it is still in transit, moving the shipment to `RETURNED`. This fires the compensating return described in §2.8: the parent order transitions to `CANCELLED`, the order's `animal_count` is added back into the VFD's `remaining_animal_count` with a `version` increment, and the mill's `pending_order_count` decrements by one. Rejecting the shipment at receipt — moving it to `REJECTED_AT_RECEIPT` — fires the identical compensation.

### 3.7. Cancelling an Order Before Shipment

Before a shipment exists, an order may be cancelled outright. The producer on the order may cancel it, or an inspector may cancel it as an administrative override. The order must currently be `SUBMITTED` or `VALIDATED` (otherwise `ERR_INVALID_STATE`); when the actor is a `Producer`, `X-User-ID` must equal the order's `producer_id` (otherwise `ERR_FORBIDDEN`). Cancelling a `SUBMITTED` order moves it to `CANCELLED` with no further effect. Cancelling a `VALIDATED` order fires the compensating return: the VFD's `remaining_animal_count` is incremented by the order's `animal_count`, the VFD's `version` increments, the mill's `pending_order_count` decrements by one, and the order's `WithdrawalPlan` is left behind in `PROVISIONAL` status as an orphan kept for audit.

### 3.8. Residue Cases and Clinic Compliance Penalties

An `Inspector` opens a `ResidueCase` on a producer by supplying the `feed_order_id` under investigation, the `detected_at` timestamp when residue was detected, an `investigator_id`, and optionally a `residue_ppb` reading and a `tolerance_ppb` regulatory limit. The case starts in `OPEN` status. From `OPEN` an inspector may move it to `UNDER_INVESTIGATION` (any other starting state is rejected with `ERR_INVALID_STATE`). From `OPEN` or `UNDER_INVESTIGATION` an inspector may dismiss the case, moving it to `DISMISSED`. From `UNDER_INVESTIGATION` an inspector may confirm a violation by supplying the now-known `residue_ppb` and `tolerance_ppb`, moving the case to `CONFIRMED_VIOLATION`; a case in any other starting state is rejected with `ERR_INVALID_STATE`, and the request is rejected with `ERR_INVALID_REQUEST` if either value is absent.

Confirming a violation triggers two calculations. First, the case's `severity_tier` is computed from the ratio of `residue_ppb` to `tolerance_ppb`: if the ratio is strictly less than 2.0 the case's `severity_tier` is `TIER_1`; otherwise if the ratio is strictly less than 5.0 the `severity_tier` is `TIER_2`; otherwise the `severity_tier` is `TIER_3`. Second, the penalty deducted from the issuing clinic's `compliance_score` is computed as a per-tier marginal sum, rounded per tier and then added. The deduction starts at zero. If the ratio exceeds 1.0, add the first-tier marginal: take the smaller of the ratio and 2.0, subtract 1.0, round the result half-up to an integer, and multiply by 50. If the ratio exceeds 2.0, add the second-tier marginal: take the smaller of the ratio and 5.0, subtract 2.0, round half-up to an integer, and multiply by 150. If the ratio exceeds 5.0, add the third-tier marginal: subtract 5.0 from the ratio, round half-up to an integer, and multiply by 400. Finally, add a flat administrative penalty of 100 for any confirmed violation. The order of operations is load-bearing: each tier's marginal amount is rounded before summing, because rounding after summing would produce different totals. The resulting `penalty_score_deduction` is recorded on the case and subtracted from the issuing clinic's `compliance_score`, walking the chronological path from the feed order back through its VFD to its veterinarian and finally to that veterinarian's clinic. If the deduction takes the clinic's `compliance_score` below 700, the clinic's `audit_ready` flag flips to false per §2.9.

### 3.9. Audit Bundles and Producer Discipline

An `Inspector` opens an `AuditBundle` on a producer by supplying `window_start` and `window_end` (no ordering constraint between the two is enforced). The bundle starts in `OPEN` status with `opened_at` set to the current logical time, `produced_record_count` initialized to zero, and `required_record_count` computed from the producer's records that intersect the window under the semantics defined in §2.10. The populations counted are the producer's `VfdAuthorization` records, the producer's `FeedOrder` records, the `FeedShipment` records of those included orders, and the `DistributorAcknowledgment` records belonging to the feed mill of any included order. For each population, a record counts when its `created_at` is strictly before `window_end` and either it has not terminated or its terminal timestamp is greater than or equal to `window_start`.

The producer then discharges the audit by marking records produced; the bundle must be `OPEN` (otherwise `ERR_INVALID_STATE`), and each such action increments `produced_record_count` by one — possibly beyond `required_record_count`. When the inspector believes the production is complete, the inspector closes the audit. Closing requires the bundle to be `OPEN` and requires `produced_record_count` to equal `required_record_count` exactly; any inequality — shortfall or excess — is rejected with `ERR_AUDIT_INCOMPLETE` (HTTP 409). On success the bundle transitions to `COMPLETE`. Alternatively, an inspector may mark an `OPEN` bundle as `DEFICIENT` (any other starting state is rejected with `ERR_INVALID_STATE`); this transitions the bundle to `DEFICIENT`, flips the producer's `status` to `SUSPENDED`, and cascades every `VfdAuthorization` the producer holds in a non-terminal state into `EXPIRED`, firing the per-VFD feed-order cancellation cascade described in §3.4.

### 3.10. Distributor Acknowledgment Letters

Before a mill may lawfully ship VFD feed to a downstream distributor, it must hold an acknowledgment letter from that distributor covering the specific drug. Either a `FeedMillOperator` or an `Inspector` records a `DistributorAcknowledgment` against a feed mill — no ownership check binds a `FeedMillOperator` caller's `X-User-ID` to the path mill — by supplying the `distributor_name`, the `covers_drug_id` of the drug the letter covers, and the verbatim `statement_text` of the letter. At recording time `acknowledged_at` is set to the current logical time and `status` becomes `ACKNOWLEDGED`. The acknowledgment lifecycle includes `PENDING` and `LAPSED` statuses, although this API exposes no endpoint that transitions a letter into them; only an `ACKNOWLEDGED` letter satisfies the ship-time check described in §3.6. Acknowledgments are listed per mill with optional `covers_drug_id` and `status` filters, or across mills with optional filters on `covers_drug_id`, `feed_mill_id`, and `status`.

### 3.11. Read Access Across the Registry

Most entities are readable by all four roles. Single-record reads exist for clinics, veterinarians, producers, animal groups, drugs, VCPR verifications, VFD authorizations, feed mills, feed orders, feed shipments, withdrawal plans, distributor acknowledgments, residue cases, and audit bundles; the broad-read set is available to `Inspector`, `Veterinarian`, `FeedMillOperator`, and `Producer`. List endpoints narrow by role. Clinics are listed by `Inspector` and `FeedMillOperator` with an optional `state_code` filter. Veterinarians are listed per clinic by `Inspector` and `FeedMillOperator`. Producers are listed by `Inspector` and `FeedMillOperator` with optional `state_code` and `status` filters. Animal groups are listed per producer by `Inspector`, `Veterinarian`, and `Producer`. Drugs are listed by `Inspector` and `FeedMillOperator`. Feed orders are listed per mill by `Inspector`, `FeedMillOperator`, and `Producer` with optional `status`, `producer_id`, and `vfd_authorization_id` filters, and across mills by all four roles with an additional `feed_mill_id` filter. Withdrawal plans are listed per feed order — the list contains zero or one entry, because a plan exists only after validation. Residue cases are listed per producer by `Inspector`, `Veterinarian`, and `Producer` with an optional `status` filter, and across producers by all four roles with additional `producer_id` and `feed_order_id` filters. Audit bundles are listed per producer by `Inspector` and `Producer` with an optional `status` filter. A feed mill's `pending_order_count` reflects the number of its orders that have been validated and have not yet reached a final outcome — incremented when an order is validated and decremented when the order is delivered, cancelled out of `VALIDATED`, returned, or rejected at receipt — and is exposed on the mill record itself.

## 4. Endpoint Definitions

Endpoints that create a new resource return HTTP 201 with the created resource in `data`. Endpoints that modify an existing resource, trigger a state transition, or perform a read return HTTP 200. All list endpoints paginate per §2.3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /vfd/_clock/set_current_utc | Advance the logical clock to a supplied timestamp, firing time-driven cascades | Inspector |
| POST | /vfd/clinics | Register a veterinary clinic | Inspector |
| GET | /vfd/clinics/{id} | Get a clinic | Inspector, Veterinarian, FeedMillOperator, Producer |
| GET | /vfd/clinics | List clinics | Inspector, FeedMillOperator |
| POST | /vfd/clinics/{id}/veterinarians | Register a veterinarian under a clinic | Inspector |
| GET | /vfd/veterinarians/{id} | Get a veterinarian | Inspector, Veterinarian, FeedMillOperator, Producer |
| GET | /vfd/clinics/{id}/veterinarians | List veterinarians of a clinic | Inspector, FeedMillOperator |
| POST | /vfd/veterinarians/{id}/suspend | Suspend a veterinarian; cascades VFD expiration | Inspector |
| POST | /vfd/veterinarians/{id}/reinstate | Reinstate a suspended veterinarian | Inspector |
| POST | /vfd/veterinarians/{id}/revoke | Revoke a veterinarian's license | Inspector |
| POST | /vfd/producers | Register a livestock producer | Inspector |
| GET | /vfd/producers/{id} | Get a producer | Inspector, Veterinarian, FeedMillOperator, Producer |
| GET | /vfd/producers | List producers | Inspector, FeedMillOperator |
| POST | /vfd/producers/{id}/animal-groups | Register an animal group under a producer | Producer, Inspector |
| GET | /vfd/animal-groups/{id} | Get an animal group | Inspector, Veterinarian, FeedMillOperator, Producer |
| GET | /vfd/producers/{id}/animal-groups | List animal groups of a producer | Inspector, Veterinarian, Producer |
| POST | /vfd/drugs | Register a VFD drug | Inspector |
| GET | /vfd/drugs/{id} | Get a drug | Inspector, Veterinarian, FeedMillOperator, Producer |
| GET | /vfd/drugs | List drugs | Inspector, FeedMillOperator |
| POST | /vfd/vcp-verifications | Record a VCPR verification | Veterinarian |
| GET | /vfd/vcp-verifications/{id} | Get a VCPR verification | Inspector, Veterinarian, FeedMillOperator |
| GET | /vfd/vcp-verifications | List VCPR verifications | Inspector, Veterinarian, FeedMillOperator |
| POST | /vfd/vcp-verifications/{id}/revoke | Revoke a VCPR | Veterinarian |
| POST | /vfd/vfd-authorizations | Issue a VFD; supports optional `supersedes_id` for replacement | Veterinarian |
| GET | /vfd/vfd-authorizations/{id} | Get a VFD | Inspector, Veterinarian, FeedMillOperator, Producer |
| GET | /vfd/vfd-authorizations | List VFDs | Inspector, Veterinarian, FeedMillOperator, Producer |
| GET | /vfd/producers/{id}/vfd-authorizations | List VFDs for a producer | Inspector, Veterinarian, FeedMillOperator, Producer |
| POST | /vfd/vfd-authorizations/{id}/revoke | Issuing vet revokes a VFD | Veterinarian |
| POST | /vfd/feed-mills | Register a feed mill | Inspector |
| GET | /vfd/feed-mills/{id} | Get a feed mill | Inspector, Veterinarian, FeedMillOperator, Producer |
| POST | /vfd/feed-mills/{id}/feed-orders | Submit a feed order against a VFD | FeedMillOperator |
| GET | /vfd/feed-orders/{id} | Get a feed order | Inspector, Veterinarian, FeedMillOperator, Producer |
| GET | /vfd/feed-mills/{id}/feed-orders | List feed orders for a mill | Inspector, FeedMillOperator, Producer |
| GET | /vfd/feed-orders | Filtered list of feed orders across mills | Inspector, FeedMillOperator, Producer, Veterinarian |
| POST | /vfd/feed-orders/{id}/validate | Validate a feed order against its VFD | FeedMillOperator |
| POST | /vfd/feed-orders/{id}/reject | Reject a feed order | FeedMillOperator |
| POST | /vfd/feed-orders/{id}/cancel | Cancel a feed order | Producer, Inspector |
| POST | /vfd/feed-orders/{id}/ship | Ship a validated feed order | FeedMillOperator |
| GET | /vfd/feed-shipments/{id} | Get a shipment | Inspector, Veterinarian, FeedMillOperator, Producer |
| GET | /vfd/feed-orders/{id}/feed-shipments | List shipments for an order | Inspector, Veterinarian, FeedMillOperator, Producer |
| POST | /vfd/feed-shipments/{id}/deliver | Confirm delivery | Producer |
| POST | /vfd/feed-shipments/{id}/return | Return shipment | Producer |
| POST | /vfd/feed-shipments/{id}/reject-receipt | Reject at receipt | Producer |
| GET | /vfd/withdrawal-plans/{id} | Get a withdrawal plan | Inspector, Veterinarian, FeedMillOperator, Producer |
| GET | /vfd/feed-orders/{id}/withdrawal-plans | List withdrawal plans for an order | Inspector, Veterinarian, FeedMillOperator, Producer |
| POST | /vfd/feed-mills/{id}/distributor-acknowledgments | Record a distributor acknowledgment letter | FeedMillOperator, Inspector |
| GET | /vfd/feed-mills/{id}/distributor-acknowledgments | List acknowledgments for a mill | Inspector, FeedMillOperator |
| GET | /vfd/distributor-acknowledgments | List acknowledgments across mills | Inspector, FeedMillOperator |
| GET | /vfd/distributor-acknowledgments/{id} | Get an acknowledgment | Inspector, FeedMillOperator |
| POST | /vfd/producers/{id}/residue-cases | Open a residue case on a producer | Inspector |
| GET | /vfd/residue-cases/{id} | Get a residue case | Inspector, Veterinarian, FeedMillOperator, Producer |
| GET | /vfd/producers/{id}/residue-cases | List residue cases for a producer | Inspector, Veterinarian, Producer |
| GET | /vfd/residue-cases | List residue cases across producers | Inspector, Veterinarian, Producer, FeedMillOperator |
| POST | /vfd/residue-cases/{id}/open-investigation | Begin investigation | Inspector |
| POST | /vfd/residue-cases/{id}/confirm | Confirm residue violation | Inspector |
| POST | /vfd/residue-cases/{id}/dismiss | Dismiss a residue case | Inspector |
| POST | /vfd/producers/{id}/audit-bundles | Open an audit on a producer | Inspector |
| GET | /vfd/audit-bundles/{id} | Get an audit bundle | Inspector, Producer |
| GET | /vfd/producers/{id}/audit-bundles | List audit bundles for a producer | Inspector, Producer |
| POST | /vfd/audit-bundles/{id}/record-produced | Mark a record produced for the audit | Producer |
| POST | /vfd/audit-bundles/{id}/close | Close audit as COMPLETE | Inspector |
| POST | /vfd/audit-bundles/{id}/mark-deficient | Mark audit DEFICIENT; cascades producer suspension | Inspector |

## 5. Error Code Catalogue

Trigger conditions for each error are described in §2 and §3.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 400 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_EXTRA_LABEL_USE | 422 |
| ERR_SPECIES_CLASS_MISMATCH | 422 |
| ERR_VCPR_NOT_VERIFIED | 422 |
| ERR_RESIDUE_CASE_OPEN | 422 |
| ERR_VFD_EXPIRED | 409 |
| ERR_VFD_NOT_USABLE | 409 |
| ERR_VFD_DURATION_EXCEEDED | 422 |
| ERR_VFD_QUOTA_EXCEEDED | 409 |
| ERR_PRODUCER_SUSPENDED | 409 |
| ERR_VET_INACTIVE | 409 |
| ERR_ACK_MISSING | 422 |
| ERR_AUDIT_INCOMPLETE | 409 |
| ERR_DUPLICATE_DRUG_CODE | 409 |
| ERR_DUPLICATE_PREMISE | 409 |
| ERR_DUPLICATE_FDA_REG | 409 |
| ERR_DUPLICATE_CLINIC_LICENSE | 409 |
