# Weigh Station Bypass API — Product Requirements Document

## 1. Introduction

Commercial motor carriers surrender driver-hours and fuel every time a truck leaves the highway to queue at a weigh station. Bypass programs exist so that credentialed, demonstrably safe fleets can roll past open stations at highway speed, and such a program lives or dies on two things: the integrity of the safety data behind each bypass, and an audit trail that a state enforcement office can still trust months after the fact. This document specifies the Weigh Station Bypass API, a service that operates the full program end to end — carrier enrollment gated on safety scores, per-vehicle transponder and mobile-app credential provisioning, a deterministic roadside decision engine governed by per-state rules, per-vehicle subscription billing with credit handling, dispute adjudication under segregation of duties, and inspection-reduction reporting that quantifies the program's value to the carrier.

Four operator constituencies and two machine feeds converge on the API. A platform operator onboards and terminates carriers and controls the service's logical clock; state program offices maintain per-state rule configurations and the station registry; compliance officers approve enrollments, adjudicate disputes, and decide eligibility waivers; carrier-side fleet managers run their own vehicles, credentials, subscriptions, and disputes; safety-score and inspection records arrive through one machine account while roadside approach events arrive through another. Every bypass decision is computed against the ruleset version pinned at decision time, every dollar is tracked in integer cents against an append-only credit ledger, and every cascade triggered by a write is fully applied and visible in that write's response and in all subsequent reads. All resources are served under the `/api` prefix.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contract formats, and cross-cutting principles that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the capacity in which they act. The platform recognizes exactly seven roles. `PlatformAdmin` is the platform operator: carrier onboarding and termination, and control of the logical clock. `StateProgramManager` represents a state program office and maintains per-state rule configurations and the station registry. `ComplianceOfficer` is the safety and compliance reviewer who approves and suspends carriers, adjudicates disputes, and decides eligibility overrides. `CarrierManager` is a carrier-side fleet manager and may act only on its own carrier's resources. `SafetyDataFeed` is the machine account for the FMCSA-style safety-score feed and the inspection feed. `TelematicsGateway` is the machine account for roadside approach event ingestion. `FinanceAdmin` runs billing: period closes and payment recording.

A request missing either header, or naming a role outside this list, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not admitted by the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403); the carrier lifecycle transition endpoint applies this rule per target state, so a `PlatformAdmin` asking for `ACTIVE`, or a `ComplianceOfficer` asking for `TERMINATED`, is refused at the role gate rather than at the state machine.

Identity semantics differ by role. When `X-User-Role` is `CarrierManager`, `X-User-ID` is the `id` of the acting `Carrier`; ownership checks on any resource that references a `Carrier` compare the resource's carrier foreign key to `X-User-ID`. When `X-User-Role` is `PlatformAdmin`, `StateProgramManager`, `ComplianceOfficer`, `SafetyDataFeed`, `TelematicsGateway`, or `FinanceAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example as `decided_by` on an eligibility override, or as `first_reviewer_id` and `appeal_reviewer_id` on a dispute) but never compares it to any entity's `id`.

Ownership resolution depends on the endpoint's shape. For creation requests that carry `carrier_id` in the body — vehicle registration, subscription creation, override requests — the comparison is direct: the body's `carrier_id` must equal `X-User-ID`. For requests that reference a vehicle, credential, subscription, or dispute — whether the identifier appears in the path or in a body field such as `vehicle_id` or `bypass_event_id` — ownership resolves through the referenced resource back to its carrier. When the referenced resource does not exist, ownership is unresolvable and the existence check described in §2.10 produces the 404 response instead. A resolved reference whose carrier differs from `X-User-ID` is rejected with `ERR_CARRIER_OWNERSHIP_MISMATCH` (HTTP 403). Ownership screening applies to every `CarrierManager` write: vehicle creation and status changes, credential provisioning and transitions, subscription creation and cancellation, dispute intake and appeals, and override requests.

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

List endpoints paginate through two query parameters. `limit` caps the page size: it defaults to 10, accepts a minimum of 1, and accepts a maximum of 100. `offset` skips that many records from the start of the result set and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside the 1-to-100 range, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list is sorted by `created_at` in ascending order, with records that share a `created_at` ordered by creation sequence, earliest created first. The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more` alongside the request identifiers; `has_more` is true exactly when `offset` plus the number of records returned is less than `total_count`.

Collections support exact-match filtering through query parameters named after the underlying fields: stations filter by `state_program_config_id` and `operational_status`; vehicles by `carrier_id` and `service_status`; credentials by `carrier_id`, `vehicle_id`, and `status`; safety-score snapshots by `carrier_id`; bypass events by `carrier_id`, `vehicle_id`, `station_id`, and `decision`; disputes by `carrier_id`, `bypass_event_id`, and `status`; eligibility overrides by `carrier_id`, `status`, and `approved_against_snapshot_id`; subscriptions by `carrier_id`, `vehicle_id`, `status`, and `payment_standing`; invoices by `carrier_id` and `status`; inspection reports by `carrier_id` and `vehicle_id`.

### 2.4. The Logical Clock and Date Semantics

The service keeps its own logical clock, and every occurrence of "today" or "now" in this document refers to that clock — never to the host's wall clock. At startup, before any client has advanced it, the logical clock reads exactly `2026-08-01T00:00:00Z`; it never silently falls back to wall-clock time. All date comparisons in the business rules — enrollment windows, pause accrual, dispute windows, billing periods, invoice due dates, feed staleness bounds — are evaluated against this clock.

A `PlatformAdmin` may advance the logical clock through a test-driving capability that accepts a target instant in `to_iso8601` — any parseable ISO 8601 instant is accepted, including one earlier than the current reading, while a missing or unparseable value is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Setting the clock synchronously runs the materialization sweep, in this order of concern: eligibility overrides whose window has been reached move from `APPROVED` to `ACTIVE`, and overrides whose window has ended move from `ACTIVE` to `EXPIRED`, each triggering a posture recompute and, where the recomputed posture is `INELIGIBLE`, the safety deactivation cascade of §3.2; subscriptions whose start date has been reached move from `SCHEDULED` to `ACTIVE`, and any subscription in `SCHEDULED`, `ACTIVE`, or `PAUSED` whose end date has passed closes with `closed_reason` `EXPIRED`; and issued invoices whose due date has passed flip from `ISSUED` to `PAST_DUE`, propagating payment standing to the carrier's subscriptions as described in §3.4. The capability's response reports the new `current_utc` alongside sweep tallies: `overrides_activated`, `overrides_expired`, `subscriptions_activated`, `subscriptions_expired`, and `invoices_marked_past_due`. All sweep effects are applied before the response is returned; there is no eventual consistency window.

### 2.5. Common Resource Properties

Most resources share a standard identity block. `id` is a server-minted UUID with no type prefix, rendered in the canonical RFC 4122 string form — 32 lowercase hexadecimal digits in five hyphen-separated groups of 8, 4, 4, 4, and 12 (for example `550e8400-e29b-41d4-a716-446655440000`), never the dashless 32-character hex form. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `updated_at` refreshes on every mutation of the resource. `version` is a system-managed integer that begins at 1 when the resource is created and increments by one on every mutation, and it is the value that optimistic concurrency tokens are compared against (§2.9).

Nine resource types carry the full identity block: carriers, state program configs, stations, vehicles, bypass credentials, vehicle subscriptions, bypass disputes, eligibility overrides, and invoices. Three record types are append-only feed or audit records and carry only `id` and `created_at`: safety-score snapshots, bypass events, and inspection reports. On those records, both `updated_at` and `version` are absent.

### 2.6. Registry Uniqueness and Feed Idempotency

Several identifiers act as global registry keys, and every collision is rejected with HTTP 409. A carrier's `dot_number` must be globally unique (`ERR_DUPLICATE_DOT_NUMBER`), a state program config's `state_code` may be registered once (`ERR_DUPLICATE_STATE_CONFIG`), and a station's `station_code` is unique across the platform (`ERR_DUPLICATE_STATION_CODE`). On the fleet side, a vehicle's `vin` (`ERR_DUPLICATE_VIN`) and a credential's `device_serial` (`ERR_DUPLICATE_DEVICE_SERIAL`) are each globally unique.

Roadside and workflow records carry their own idempotency and exclusivity guards. The triple of `vehicle_id`, `station_id`, and `approach_at` identifies a bypass approach: a feed that redelivers the same approach is a conflict (`ERR_DUPLICATE_BYPASS_EVENT`), not a second event. A bypass event may have at most one dispute whose status is `OPENED`, `UPHELD`, or `APPEALED` (`ERR_DISPUTE_ALREADY_OPEN`). A vehicle may hold at most one credential per `device_type` with a status of `PROVISIONED`, `ACTIVE`, or `SUSPENDED` (`ERR_CREDENTIAL_TYPE_ALREADY_ACTIVE`) — only deactivation frees the slot for a replacement device. Finally, a carrier's billing history is closed exactly once per period: a close request for a month already present in `closed_billing_periods` is rejected with `ERR_BILLING_PERIOD_ALREADY_CLOSED`.

### 2.7. Immutable Roadside Decisions and Ruleset Pinning

A bypass event is an audit record, not a mutable workflow object. Its `decision` and `decision_reasons` are computed at creation and never change afterward, and the same is true of every supporting fact the engine froze onto the record: the `selected_credential_id` chosen by the selector, the `ruleset_version` pinning the state config's `version` in force at decision time, the weight and credential outcomes `weight_verified` and `credentials_complete`, the deterministic screen ordinal `screen_index`, and the pre-decision monthly counters `cap_granted_before` and `cap_total_before`. The event's `carrier_id` is denormalized from the vehicle at creation and kept as an immutable audit copy, so the record still attributes the approach correctly even after fleet data evolves.

Because each event pins `ruleset_version`, later patches to a state program config are never retroactive: they raise the config's `version` and govern only decisions made after the patch. Historical events continue to describe exactly the rule set that produced them.

### 2.8. Money, Credits, and the Append-Only Ledger

All monetary amounts are integer cents; no fractional cents exist anywhere in the API. Where a computation produces a fractional cent — the per-line proration of subscription billing — each invoice line is rounded half-up to a whole cent, and only then are the rounded lines summed into the invoice gross (§3.8).

Each carrier carries an embedded, append-only `credit_ledger`. Every entry records a signed `amount_cents`, a `reason` drawn from `DISPUTE_OVERTURN_CREDIT` and `INVOICE_CREDIT_APPLICATION`, a `reference_id` pointing at the dispute or invoice that motivated the entry, and a `recorded_at` timestamp. Entries are never mutated and never removed. The carrier's `credit_balance_cents` is, by invariant, exactly the sum of `amount_cents` over all ledger entries, and it is recomputed from the ledger after every append — never incrementally adjusted — so the balance observed at any instant always equals the ledger sum. Credits enter the ledger when a dispute is overturned and leave it when they are applied against invoices; both flows are detailed in §3.6 and §3.8.

### 2.9. Optimistic Concurrency Control

Three writes require the client to present the version of the parent entity it last observed. Posting a safety-score snapshot requires `expected_carrier_version`; requesting an eligibility override requires `expected_carrier_version`; patching a state program config requires `expected_state_program_config_version`. In each case the token is a non-optional input field and must equal the parent entity's current `version` at write time. A mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412): a feed operating on a stale carrier view cannot silently reorder the score history, and a rule edit based on a superseded config cannot silently interleave with another edit — the rejected writer must re-read the parent and re-apply its intent on the fresh version. Endpoints not named in this section do not accept any version field.

### 2.10. Validation Order and Error Surface

Every request is screened against a fixed ladder of checks, and a request that fails an earlier rung is rejected with that rung's error without ever reaching later rungs. The ladder, from first to last:

1. **User context.** Both headers present and the role recognized — otherwise `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role admission.** The role appears in the endpoint's authorized list, including the per-target-state role rules on the carrier transition endpoint — otherwise `ERR_FORBIDDEN_ROLE`.
3. **Carrier ownership.** For `CarrierManager` writes, `X-User-ID` must match the carrier in scope — otherwise `ERR_CARRIER_OWNERSHIP_MISMATCH` (where the reference is unresolvable, the next rung answers instead).
4. **Existence.** Path- and body-referenced resources are verified left to right — carrier, state config, station, vehicle, credential, bypass event, dispute, override, subscription, invoice — and the first missing reference yields its `ERR_CARRIER_NOT_FOUND`, `ERR_STATE_PROGRAM_CONFIG_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_CREDENTIAL_NOT_FOUND`, `ERR_BYPASS_EVENT_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, `ERR_OVERRIDE_NOT_FOUND`, `ERR_SUBSCRIPTION_NOT_FOUND`, or `ERR_INVOICE_NOT_FOUND`. A read of a safety-score snapshot or an inspection report — the two append-only record types, which carry no resource-specific catalogue entry — yields `ERR_NOT_FOUND` (HTTP 404) when the id does not exist.
5. **State-machine legality.** The target resource must be in a from-state that permits the requested transition, with terminal states locked and same-state no-ops rejected — otherwise `ERR_INVALID_STATE_TRANSITION`.
6. **Concurrency token.** Where §2.9 applies, the presented version must match — otherwise `ERR_STALE_VERSION`.
7. **Business safety gates, in their pinned relative order.** The enrollment-approval gate (`ERR_CARRIER_INELIGIBLE_FOR_APPROVAL`) precedes the reinstatement gate (`ERR_CARRIER_STILL_INELIGIBLE`), which precedes the child-write gate requiring an `ACTIVE` carrier (`ERR_CARRIER_NOT_ACTIVE`), which precedes the credential posture gate (`ERR_CARRIER_NOT_BYPASS_ELIGIBLE`), which precedes the vehicle in-service gate (`ERR_VEHICLE_NOT_IN_SERVICE`).
8. **Referential prerequisites.** Snapshot presence for override requests and approvals — otherwise `ERR_NO_SAFETY_SNAPSHOT`.
9. **Temporal sanity.** Date and time bounds — `ERR_INVALID_DATE_RANGE` for inverted or out-of-range date windows, `ERR_FUTURE_APPROACH` and `ERR_STALE_APPROACH` for approach timestamps, `ERR_FUTURE_INSPECTION` for inspection timestamps, `ERR_BILLING_PERIOD_NOT_CLOSABLE` for unelapsed periods.
10. **Window overlaps.** Override windows first (`ERR_OVERRIDE_WINDOW_OVERLAP`), then subscription windows (`ERR_SUBSCRIPTION_WINDOW_OVERLAP`).
11. **Dispute target checks, in order.** The event's decision must be `PULL_IN` (`ERR_EVENT_NOT_DISPUTABLE`), and only then is the filing window examined (`ERR_DISPUTE_WINDOW_EXPIRED`).
12. **Field ranges and formats.** Required fields present, enum members valid, numeric ranges respected — `ERR_INVALID_REQUEST`, `ERR_INVALID_ISS_SCORE`, and `ERR_CREDIT_AMOUNT_OUT_OF_RANGE`. On the transition endpoints, a requested target state outside the endpoint's accepted target set (for example `to_status` `ENROLLED` on the carrier transition endpoint) is an enum-member failure under this rung; `ERR_INVALID_STATE_TRANSITION` is reserved for accepted targets that the resource's current state cannot reach.
13. **Uniqueness and exclusivity.** The registry and idempotency guards of §2.6.
14. **Segregation of duties.** Appeal review by a different officer — otherwise `ERR_SEGREGATION_OF_DUTIES`.
15. **Fiscal gates, in their pinned relative order.** The covering-subscription gate (`ERR_NO_ACTIVE_SUBSCRIPTION`) precedes the past-due standing gate (`ERR_CARRIER_PAST_DUE`); for payments, the exact-amount check (`ERR_PAYMENT_AMOUNT_MISMATCH`) precedes the already-paid check (`ERR_INVOICE_NOT_PAYABLE`).

Rung numbering here is semantic, not decorative: when a request violates two rules, the error the client receives is always the one from the earlier rung.

## 3. Business Logic & Workflows

### 3.1. Carrier Onboarding and the Enrollment Lifecycle

A carrier enters the program when a `PlatformAdmin` onboards it with its `dot_number` and `legal_name`. New carriers begin with `status` `ENROLLED`, an `eligibility_status` of `NOT_EVALUATED`, a `credit_balance_cents` of zero, an empty `credit_ledger`, and an empty `closed_billing_periods` history. Reading a carrier back exposes all of this — posture, ledger, closed periods, and the current `version` — to every authenticated role.

Enrollment is not activation. A `ComplianceOfficer` moves a carrier from `ENROLLED` to `ACTIVE` by submitting `to_status` `ACTIVE`, and the transition is permitted only when the carrier's posture is `ELIGIBLE` or `CONDITIONAL`; a carrier whose posture is `NOT_EVALUATED` or `INELIGIBLE` is rejected with `ERR_CARRIER_INELIGIBLE_FOR_APPROVAL` (HTTP 422). Once active, a `ComplianceOfficer` may suspend the carrier (`ACTIVE` to `SUSPENDED`) and later reinstate it (`SUSPENDED` to `ACTIVE`), and this loop may cycle without limit. Reinstatement carries its own gate: the posture must be anything other than `INELIGIBLE`, or the request fails with `ERR_CARRIER_STILL_INELIGIBLE` (HTTP 422). Two subtleties define the manual loop. Manual suspension does not cascade — a suspended carrier's credentials and subscriptions are left exactly as they were. And reinstatement does not resurrect credentials that were suspended for safety reasons: any credential sitting in `SUSPENDED` with `status_reason` `SAFETY_INELIGIBLE` stays suspended until a per-credential reactivation (§3.4).

Termination is the exclusive, terminal act of a `PlatformAdmin`, available from `ENROLLED`, `ACTIVE`, or `SUSPENDED`, and it cascades through everything the carrier owns: every credential not yet `DEACTIVATED` becomes `DEACTIVATED` with `status_reason` `CARRIER_TERMINATED`; every subscription in `SCHEDULED`, `ACTIVE`, or `PAUSED` closes with `closed_reason` `TERMINATED_CARRIER`, its `service_end_date` pulled back to today when it still lies in the future; and every eligibility override in `REQUESTED`, `APPROVED`, or `ACTIVE` is revoked — a bookkeeping revocation only, which does not run the posture recompute (or the safety cascade) of §3.7. Each lifecycle transition — approval, suspension, reinstatement, termination — increments the carrier's `version` by exactly one. As noted in §2.1, the role gate is per target state: `ACTIVE` and `SUSPENDED` belong to `ComplianceOfficer`, `TERMINATED` to `PlatformAdmin`, and crossing that line is `ERR_FORBIDDEN_ROLE`.

A carrier's lifecycle status also gates what may be written beneath it. Registering vehicles, provisioning credentials, creating subscriptions, and opening disputes all require the carrier to be `ACTIVE`; against any other status the write fails with `ERR_CARRIER_NOT_ACTIVE` (HTTP 409). Eligibility override requests are the deliberate exception: they are accepted for `ENROLLED`, `ACTIVE`, and `SUSPENDED` carriers and rejected only for a `TERMINATED` carrier, again as `ERR_CARRIER_NOT_ACTIVE`.

### 3.2. Safety Scores, Eligibility Posture, and Safety-Driven Deactivation

Safety data arrives through the `SafetyDataFeed` account as score snapshots carrying `carrier_id`, an `iss_score` from 0 to 100 where higher is worse (outside that range: `ERR_INVALID_ISS_SCORE`, HTTP 400), a `safety_rating` of `SATISFACTORY`, `CONDITIONAL`, or `UNSATISFACTORY`, a `source` of `FMCSA_FEED` or `MANUAL_AUDIT`, and the `effective_date` on which the score takes effect — never a future date, or the post fails with `ERR_INVALID_DATE_RANGE`. The write is concurrency-checked per §2.9 through `expected_carrier_version`, so a feed that read the carrier before another snapshot landed cannot silently reorder the score history.

The carrier keeps a derived pointer to its latest snapshot: `latest_snapshot_id` names the snapshot with the greatest `effective_date`, ties broken toward the most recently created record, and `latest_iss_score` and `latest_safety_rating` mirror that snapshot's values. All three are null until the first snapshot arrives.

From the latest snapshot and any in-force override, the service derives the carrier's posture, `eligibility_status`. The evaluation order is fixed: if the carrier has an eligibility override that is `ACTIVE` with a window covering today, posture is forced to `ELIGIBLE` regardless of the score. Otherwise, with no snapshot at all, posture is `NOT_EVALUATED`. Otherwise a rating of `UNSATISFACTORY`, or an `iss_score` of 75 or higher, yields `INELIGIBLE`; failing that, a rating of `CONDITIONAL`, or an `iss_score` of 50 or higher, yields `CONDITIONAL`; anything else yields `ELIGIBLE`. The boundaries are inclusive at the lower edge of each band: a score of exactly 75 is `INELIGIBLE`, 74 is `CONDITIONAL`, exactly 50 is `CONDITIONAL`, and 49 is `ELIGIBLE`.

Posture is a parallel machine on the carrier, orthogonal to the lifecycle `status`, and it has no direct API — it moves only in response to snapshots and override force changes. A first snapshot moves `NOT_EVALUATED` into whichever of the three bands its rating and score dictate. Thereafter a degrading snapshot moves `ELIGIBLE` to `CONDITIONAL`, or from either band to `INELIGIBLE`; an improving snapshot moves `INELIGIBLE` or `CONDITIONAL` upward, `INELIGIBLE` to `ELIGIBLE` or `CONDITIONAL`, and `CONDITIONAL` to `ELIGIBLE`. An override entering force lifts the carrier to `ELIGIBLE` from `CONDITIONAL` or `INELIGIBLE`; an override leaving force — expiring, revoked, or gone stale — drops the carrier back into whatever band the latest snapshot dictates.

Entering `INELIGIBLE` from `ELIGIBLE` or `CONDITIONAL` fires the safety deactivation cascade, and its effects are visible in the triggering response itself: every credential of the carrier in `ACTIVE` moves to `SUSPENDED` with `status_reason` `SAFETY_INELIGIBLE`, each such suspension pauses its vehicle's subscription (`ACTIVE` to `PAUSED`, `paused_at` set to today), and the carrier's `version` increments by one. A first evaluation that moves `NOT_EVALUATED` directly into `INELIGIBLE` does not fire the cascade — such a carrier can hold no `ACTIVE` credentials — so the carrier's `version` then rises only by the snapshot write's own increment. Posture never touches the lifecycle machine. An `ACTIVE` carrier whose posture collapses keeps its `ACTIVE` status — but with all credentials suspended, and every roadside approach it makes will pull in at the carrier-eligibility check of §3.5. Symmetrically, a `SUSPENDED` carrier whose posture recovers is not automatically reinstated; only a `ComplianceOfficer` can move it back through the manual gate of §3.1. Posting a snapshot also increments the carrier's `version` by one, and a snapshot that becomes the carrier's latest can strand an in-force override that was approved against an older snapshot — that flip to `STALE`, and its own cascade, is the subject of §3.7.

### 3.3. State Programs and the Station Registry

Bypass rules are per state, and a `StateProgramManager` authors each state's rule set as a state program config. The config's `state_code` is its two-letter, globally unique key. Its rule fields all carry defaults, so a minimal creation needs only the code: `iss_refusal_threshold` defaults to 75 and must sit between 50 and 100 inclusive; `random_pull_in_rate_bps` defaults to 0 and spans 0 to 10000; `bypass_rate_cap_bps` defaults to 10000 and spans 1 to 10000; `hazmat_bypass_allowed` defaults to false; `requires_weight_clearance` defaults to true; and `credential_sets_required` defaults to the trio `IFTA`, `IRP`, `UCR`, accepting any subset of `IFTA`, `IRP`, `UCR`, and `HOS_LOG`.

A config's `participation_status` begins at `PILOT`. From there a `StateProgramManager` may promote it to `PARTICIPATING` or suspend it to `SUSPENDED`, and a participating state may later be suspended and restored — `PARTICIPATING` and `SUSPENDED` alternate freely. What no patch may do is return a config to `PILOT`: from `SUSPENDED` or `PARTICIPATING` back to `PILOT` is an illegal transition, rejected with `ERR_INVALID_STATE_TRANSITION`. Every patch — whether it moves participation or merely adjusts thresholds, rates, flags, or the required credential sets — must present `expected_state_program_config_version` per §2.9 and increments the config's `version` by one. Rule patches are allowed from any participation status, and because roadside events pin `ruleset_version` (§2.7), a patch governs only decisions recorded after it.

Stations are registered under a config by naming its `state_program_config_id`, along with a globally unique `station_code`, a `station_type` of `FIXED_SCALE`, `WIM_ONLY`, or `MOBILE_PATROL`, and a `supported_channel` of `TRANSPONDER`, `MOBILE_APP`, or `BOTH`. Mobile patrol units never issue bypasses — the decision engine refuses them categorically (§3.5). A station is born `OPERATIONAL`; the registry may move it to `CLOSED_TEMP` and back to `OPERATIONAL` as conditions change, or close it for good: `CLOSED_PERM` is terminal and reachable from either operational state.

### 3.4. Fleet Management, Credentials, and Subscription Service

With an `ACTIVE` carrier in place, its `CarrierManager` builds the fleet. Registering a vehicle requires `carrier_id` (which must equal the caller's identity per §2.1 and is immutable thereafter), a globally unique `vin`, the `plate_number` and `plate_state`, the `home_state_code` that later drives pilot-state billing surcharges (§3.8), the registered weight rating `gvwr_lbs` in pounds — which must be greater than zero, with violations rejected as `ERR_INVALID_REQUEST` — and optionally `hazmat_endorsed`, defaulting to false. A vehicle starts `IN_SERVICE`; its manager may set it `OUT_OF_SERVICE` and back again at will, or retire it to `RETIRED` — a terminal state reachable from either service state — and retirement cascades: every credential of the vehicle not yet `DEACTIVATED` becomes `DEACTIVATED` with `status_reason` `VEHICLE_RETIRED`, and every subscription of the vehicle in `SCHEDULED`, `ACTIVE`, or `PAUSED` closes with `closed_reason` `VEHICLE_RETIRED`, its end date pulled back to today when still in the future.

Credentials put the fleet on the bypass network. Provisioning one names the `vehicle_id`, a `device_type` of `TRANSPONDER` or `MOBILE_APP`, and a globally unique `device_serial`; the carrier must be `ACTIVE`, and the one-slot-per-type rule of §2.6 applies. The credential's `carrier_id` is denormalized from the vehicle at creation for scoping and filtering. It begins `PROVISIONED` with `status_reason` `NONE`.

Activation is the credential workflow's choke point, and its gates are evaluated in a fixed order: ownership first, then the carrier must be `ACTIVE` (`ERR_CARRIER_NOT_ACTIVE`), then the carrier's posture must be `ELIGIBLE` or `CONDITIONAL` (`ERR_CARRIER_NOT_BYPASS_ELIGIBLE`, HTTP 422), then the vehicle must be `IN_SERVICE` (`ERR_VEHICLE_NOT_IN_SERVICE`), then a covering subscription must exist — one whose status is `ACTIVE` or `PAUSED` and whose window covers today, otherwise `ERR_NO_ACTIVE_SUBSCRIPTION` (HTTP 402) — and finally the standing gate: if the carrier has any `PAST_DUE` invoice, or the covering subscription's `payment_standing` is `PAST_DUE`, activation fails with `ERR_CARRIER_PAST_DUE` (HTTP 402). When activation succeeds against a `PAUSED` covering subscription, the subscription resumes automatically — service follows the credential. The identical gate set guards reactivation from `SUSPENDED` to `ACTIVE`, and either activation records `status_reason` `NONE` on the credential.

Suspension and reactivation form an unlimited loop. A `CarrierManager` may suspend an `ACTIVE` credential manually (recorded with `status_reason` `MANUAL`), and the safety cascade of §3.2 may suspend it with `status_reason` `SAFETY_INELIGIBLE`; either way, the vehicle's `ACTIVE` subscription moves to `PAUSED` with `paused_at` set to today — billing follows service. Reactivation reverses that bookkeeping: the vehicle's `PAUSED` subscription returns to `ACTIVE`, the day count between the recorded `paused_at` date and the resume date is added to `paused_days_current_period`, and `paused_at` is cleared. Deactivation is terminal and reachable from `PROVISIONED`, `ACTIVE`, or `SUSPENDED`, whether manual — recorded with `status_reason` `MANUAL` — or by the carrier-termination and vehicle-retirement cascades. One asymmetry matters for billing: a safety suspension pauses the subscription, but a manual deactivation of an `ACTIVE` credential leaves the subscription `ACTIVE` — the carrier keeps paying until it cancels.

Subscriptions are the per-vehicle billing instrument. Creating one names `carrier_id`, `vehicle_id`, `service_start_date`, and `service_end_date`; the carrier must be `ACTIVE` and free of past-due standing (`ERR_CARRIER_PAST_DUE`). The start date must be on or after today and not after the end date, and the end date must not already be in the past — violations are `ERR_INVALID_DATE_RANGE`. Windows are closed intervals, inclusive at both ends, and a vehicle's non-`CLOSED` subscriptions may not overlap: a new window touching an existing one is rejected with `ERR_SUBSCRIPTION_WINDOW_OVERLAP`, and — unlike the override windows of §3.7 — adjacency counts as conflict here, so a start date equal to an existing subscription's end date is itself an overlap. The subscription opens as `SCHEDULED` when its start date lies in the future and as `ACTIVE` when the start date has already arrived; `payment_standing` begins at `CURRENT`.

From there the subscription evolves on two independent dimensions of the same row. On the lifecycle dimension, the clock sweep materializes `SCHEDULED` rows into `ACTIVE` when the start date arrives, and closes any of `SCHEDULED`, `ACTIVE`, or `PAUSED` with `closed_reason` `EXPIRED` once today passes the end date. A `CarrierManager` may instead cancel at any time before then: the row closes with `closed_reason` `CANCELLED`, the end date pulls back to today if it still lies ahead, and a subscription closed while `PAUSED` — by cancellation, by the expiry sweep, or by the termination and retirement cascades alike — first accrues its open pause interval, the day count between the recorded `paused_at` date and the closing date, into `paused_days_current_period`. On the standing dimension, the past-due sweep moves `payment_standing` from `CURRENT` to `PAST_DUE` across the carrier's `SCHEDULED`, `ACTIVE`, and `PAUSED` subscriptions whenever one of the carrier's invoices lapses (§3.8), and standing returns to `CURRENT` as soon as no `PAST_DUE` invoices remain. Past-due standing blocks both new subscriptions and credential activation or reactivation, as the gates above describe. A `PAUSED` row also carries `paused_at`, the date the current pause began — null unless the subscription is paused — and `paused_days_current_period`, which counts paused days within the open billing period and is consulted and reset at billing close; `closed_reason` stays null unless the row is `CLOSED`, when it records `CANCELLED`, `EXPIRED`, `TERMINATED_CARRIER`, or `VEHICLE_RETIRED`.

### 3.5. Roadside Approaches and the Bypass Decision

When a equipped vehicle nears a station, the `TelematicsGateway` records the approach with `vehicle_id`, `station_id`, and the approach instant `approach_at`. Feed timeliness bounds both ends: an approach timestamped after the logical now is `ERR_FUTURE_APPROACH` (HTTP 400), and one older than forty-eight hours before now is rejected as late-arriving with `ERR_STALE_APPROACH` (HTTP 422); the approach triple is unique per §2.6. The record may also carry `measured_weight_lbs` from the weigh-in-motion sensor — absent when no reading was captured — a `credentials_presented` list defaulting to empty, naming any of `IFTA`, `IRP`, `UCR`, and `HOS_LOG` verified at the roadside, and a `hazmat_load` flag defaulting to false. The event's `carrier_id` is denormalized from the vehicle as an immutable audit copy.

The decision engine then walks a pinned sequence of fourteen checks against the event, the station, the station's state config, the vehicle, and the carrier. The first check that fails fixes the outcome as `PULL_IN` with exactly that check's single reason code stored in `decision_reasons`; only a clean pass through all fourteen yields `BYPASS_GRANTED` with an empty `decision_reasons`. In order:

1. **Station availability.** If the station's `operational_status` is anything other than `OPERATIONAL`, the reason is `STATION_NOT_OPERATIONAL`.
2. **Station type.** A `MOBILE_PATROL` station never bypasses: `STATION_TYPE_NO_BYPASS`.
3. **State participation.** A config whose `participation_status` is `SUSPENDED` pulls everyone in: `STATE_NOT_PARTICIPATING`.
4. **Carrier lifecycle.** If the carrier's `status` is not `ACTIVE`: `CARRIER_NOT_ACTIVE`.
5. **Carrier posture.** An `eligibility_status` of `INELIGIBLE` or `NOT_EVALUATED`: `CARRIER_INELIGIBLE`.
6. **State refusal line.** If the carrier's `latest_iss_score` is at least the config's `iss_refusal_threshold`: `ISS_ABOVE_STATE_THRESHOLD` — a carrier can pass the posture gate and still be refused by a stricter state line.
7. **Vehicle status.** Anything other than `IN_SERVICE`: `VEHICLE_OUT_OF_SERVICE`.
8. **Credential presence.** With no credential of the vehicle in `ACTIVE` status: `NO_ACTIVE_CREDENTIAL`.
9. **Channel compatibility and selection.** From the vehicle's `ACTIVE` credentials, the selector drops any whose `device_type` does not match the station's `supported_channel` unless the station supports `BOTH`; if that empties the candidate set, the reason is `CHANNEL_UNSUPPORTED`. Among the survivors, a config in `PILOT` prefers `MOBILE_APP` and any other config prefers `TRANSPONDER`, with remaining ties broken toward the earliest `created_at` — never by identifier — and any further tie on an identical `created_at` broken toward the credential created first. The chosen credential is recorded as `selected_credential_id` (null whenever no credential is `ACTIVE`). Finally, in a `PILOT` state, if the selected credential is not a `MOBILE_APP` credential, the event fails as `PILOT_APP_ONLY`.
10. **Hazmat.** A `hazmat_load` approach in a state whose `hazmat_bypass_allowed` is false: `HAZMAT_NOT_PERMITTED`.
11. **Weight enforcement.** When a reading is present, it is compared against the vehicle's `gvwr_lbs` plus an allowance of five percent of the rating — 500 basis points, computed in whole pounds with any fractional pound discarded. A reading strictly above that limit fails as `OVERWEIGHT`; a reading exactly at the limit clears. This check applies whenever a reading exists, regardless of the state's `requires_weight_clearance` flag. When no reading was captured and the state does require weight clearance, the event fails as `WEIGHT_NOT_CLEARED`.
12. **Credential sets.** If the config's `credential_sets_required` is not fully contained in the event's `credentials_presented`: `CREDENTIALS_INCOMPLETE`.
13. **Deterministic random screen.** Described below; when it fires, the reason is `RANDOM_SCREEN`.
14. **Bypass rate cap.** Described below; when the cap forbids the grant, the reason is `RATE_CAP_EXCEEDED`.

The random screen is deterministic and cheap to audit. A config whose `random_pull_in_rate_bps` is zero never screens. Otherwise, divide ten thousand by the configured rate and discard the fraction to get the period N — a rate of 5,000 basis points pulls in every second approach, 500 basis points every twentieth. Each approach's ordinal is one plus the count of bypass events already recorded at the same station whose `approach_at` falls on the same calendar day; the screen fires exactly when that ordinal is a whole multiple of N, and the firing ordinal is preserved on the event as `screen_index` (null when the screen did not fire).

The rate cap keeps any single carrier's monthly bypass share inside state limits. For the bucket keyed by the carrier, the station's state, and the calendar month of `approach_at`, the engine reads two pre-decision counters and freezes them onto the event as `cap_granted_before` (bypasses already granted in the bucket) and `cap_total_before` (approaches already recorded in the bucket). The cap itself is the config's `bypass_rate_cap_bps`, halved with the fraction discarded when the carrier's posture is `CONDITIONAL`. The grant is permitted only when one more than the grants-so-far, multiplied by ten thousand, is no greater than the cap multiplied by one more than the approaches-so-far; equality permits the bypass. Evaluation order is pinned: counters are read before the decision, the decision is computed, and only then are the bucket counters and the station's screen ordinal advanced — exactly once per recorded event.

Two derived flags round out the audit record. `weight_verified` is true exactly when a reading is present and at or under the allowance limit. `credentials_complete` is true exactly when every set named in `credential_sets_required` appears in `credentials_presented`. Both feed the conservative ROI variant of §3.8. And per §2.7, the event pins `ruleset_version` to the config's `version` at decision time, so later rule patches never rewrite history.

### 3.6. Disputes, Appeals, and Credit Adjudication

A carrier that believes it was wrongly pulled in opens a dispute through its `CarrierManager`, naming the `bypass_event_id`, a free-text `reason`, and the `claimed_credit_cents` it seeks — between 1 and 100000 cents inclusive, with out-of-range amounts rejected as `ERR_CREDIT_AMOUNT_OUT_OF_RANGE` (HTTP 400). The carrier must be `ACTIVE`, and ownership resolves through the event per §2.1. Two target checks then apply in order: the event's `decision` must be `PULL_IN` — a `BYPASS_GRANTED` event has nothing to dispute and draws `ERR_EVENT_NOT_DISPUTABLE` (HTTP 422) — and the filing must come within thirty days of the approach, meaning the difference between today and the approach's calendar date may not exceed 30, or the open fails with `ERR_DISPUTE_WINDOW_EXPIRED` (HTTP 422). Section 2.6's one-open-dispute guard completes the intake. A new dispute opens as `OPENED` with its `carrier_id` denormalized from the event.

Adjudication belongs to a `ComplianceOfficer`, who submits an `outcome`. From `OPENED`, an outcome of `UPHELD` records the officer's identity in `first_reviewer_id` and stamps `adjudicated_at` with the decision time; a `credit_amount_cents` supplied alongside an `UPHELD` outcome is ignored. An outcome of `OVERTURNED` may carry an optional `credit_amount_cents` — bounded by the same 1-to-100000 range and never exceeding `claimed_credit_cents`, else `ERR_CREDIT_AMOUNT_OUT_OF_RANGE` — and sets `granted_credit_cents` to that amount, or to the full claim when no amount is given.

An overturn triggers the credit cascade. The granted amount enters the carrier's `credit_ledger` as a positive entry with reason `DISPUTE_OVERTURN_CREDIT` referencing the dispute; `credit_balance_cents` is recomputed from the ledger per §2.8; and the carrier's `version` increments exactly once per adjudication, no matter how many ledger entries the following sweep appends. That sweep then applies the new credit to money owed: it walks the carrier's unpaid invoices — those in `ISSUED` or `PAST_DUE` — oldest first by `issued_at`, ties broken by creation order, and while the balance covers an invoice's full `amount_due_cents` it appends a negative ledger entry of exactly that amount with reason `INVOICE_CREDIT_APPLICATION` referencing the invoice, marks the invoice `PAID`, and recomputes the balance before considering the next. Partial coverage is never applied. When the sweep ends and no `PAST_DUE` invoices remain, the carrier's subscriptions recover from `PAST_DUE` standing back to `CURRENT`.

A carrier that loses may appeal: from `UPHELD`, the `CarrierManager` moves the dispute to `APPEALED` for a second review. Segregation of duties governs that review — the officer adjudicating an appealed dispute must not be the officer recorded as `first_reviewer_id`, and a self-review is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). The second reviewer is recorded as `appeal_reviewer_id`, and `adjudicated_at` reflects the latest adjudication. From `APPEALED`, an outcome of `UPHELD` ends the matter at `UPHELD_FINAL`; an outcome of `OVERTURNED` applies the same credit-bounds check and the same ledger and auto-apply cascade as a first-instance overturn. `OVERTURNED` and `UPHELD_FINAL` are the dispute's terminal states.

### 3.7. Eligibility Overrides: Temporary Waivers

A carrier sliding into a poor posture band may petition for a temporary waiver. The `CarrierManager` files the request with `carrier_id`, a justifying `reason`, and a half-open window from `start_date` (inclusive) to `end_date` (exclusive) — the end date must fall after the start date, or the request fails as `ERR_INVALID_DATE_RANGE`. The write is concurrency-checked per §2.9 through `expected_carrier_version`, and filing it increments the carrier's `version` by one. Two admission rules apply: the carrier must not be `TERMINATED` (the §3.1 exception to the child-write gate, surfaced as `ERR_CARRIER_NOT_ACTIVE`), and the carrier must have at least one safety snapshot on file, since a waiver with no score history to waive is meaningless — that failure is `ERR_NO_SAFETY_SNAPSHOT` (HTTP 422). Windows for the same carrier may not overlap while any of them is `REQUESTED`, `APPROVED`, or `ACTIVE`: the comparison is half-open, so a request whose start date equals an existing window's end date is adjacent, not overlapping, and is permitted; a true intersection is rejected with `ERR_OVERRIDE_WINDOW_OVERLAP` (HTTP 409).

Decision belongs to a `ComplianceOfficer` submitting an `outcome` against a `REQUESTED` override. `REJECT` simply records `decided_by` and ends the matter — `REJECTED` is terminal. `APPROVE` re-verifies that the carrier still has a snapshot (`ERR_NO_SAFETY_SNAPSHOT`) and that the window still clears every sibling `REQUESTED`, `APPROVED`, or `ACTIVE` override (`ERR_OVERRIDE_WINDOW_OVERLAP`); it then pins `approved_against_snapshot_id` to the carrier's `latest_snapshot_id` at that instant, records `decided_by`, and — when the start date has already arrived — moves the override straight to `ACTIVE` with an immediate posture recompute. An `APPROVED` override whose start date lies ahead waits for the clock sweep, which moves it to `ACTIVE` once today reaches `start_date`; while in force it forces the carrier's posture to `ELIGIBLE` per §3.2, which can lift even an `INELIGIBLE` band — though a carrier in lifecycle `SUSPENDED` stays suspended until a manual reinstatement under §3.1.

Waivers unwind three ways, and each recomputes posture without the override. The clock sweep moves `ACTIVE` to `EXPIRED` once today reaches `end_date`. A `ComplianceOfficer` may submit `outcome` `REVOKE` against an `APPROVED` or `ACTIVE` override — it records `decided_by` like the other outcomes; against a not-yet-active approval the recompute is a no-op, since the waiver never forced posture, while revoking an in-force waiver drops the carrier back to its snapshot band. And version pinning enforces itself: whenever the carrier's latest-snapshot pointer of §3.2 moves to a snapshot other than `approved_against_snapshot_id` — including a snapshot that merely ties the pinned one's `effective_date` and wins the creation-time tie-break — an `ACTIVE` override flips to `STALE`, terminal, and posture is recomputed from the new snapshot without it. Wherever an in-force override leaves force — `EXPIRED`, `REVOKED`, or `STALE` — and the recomputed posture lands `INELIGIBLE`, the safety deactivation cascade of §3.2 fires. `REJECTED`, `REVOKED`, `EXPIRED`, and `STALE` are all terminal.

### 3.8. Billing Close, Invoices, and Return-on-Investment Reporting

Billing runs per carrier, per calendar month, and it runs late on purpose: a `FinanceAdmin` closes a period by naming `period_year` and `period_month` (the month must lie between 1 and 12, else `ERR_INVALID_REQUEST`) only after the month has fully elapsed — a period whose last day is today or still ahead is rejected with `ERR_BILLING_PERIOD_NOT_CLOSABLE` (HTTP 422) — and only once, with repeats caught by the §2.6 guard against labels already in `closed_billing_periods`. The close computes one line per subscription whose service window — `service_start_date` through the earlier of `service_end_date` and today — shares at least one day with the month; a subscription already closed by expiry before the month began has a window ending before the month starts and so contributes no line.

Each line counts its overlap with the month in inclusive days, subtracts the pause time, and bills the rest. The paused total is the subscription's accumulated `paused_days_current_period` plus — if the subscription is still `PAUSED` at close time — the days from `paused_at` through the month's final day inclusive, all confined to the overlap window; `billable_days` is the overlap minus that pause figure. Lines whose window overlapped the month are included even when their `billable_days` work out to zero, with a net of zero, and they still count toward the billed-line tally. A pilot surcharge applies per line: when a state program config exists for the vehicle's `home_state_code` and that config's `participation_status` is `PILOT` at close time, the line's `surcharge_cents` is 200; otherwise it is 0.

Pricing is tiered by volume, and the tier is an average rate, not a marginal one. The `billed_line_count` selects the tier — zero through ten lines price at `TIER_1`, eleven through fifty at `TIER_2`, fifty-one or more at `TIER_3` — and the corresponding per-vehicle rate of 1,799, 1,599, or 1,399 cents applies to every line on the invoice, so the eleventh subscribed vehicle lowers the rate for the first ten as well. Each line's `line_net_cents` is then the tier rate plus the surcharge, multiplied by the line's `billable_days`, divided by the number of days in the billing month, rounded half-up to a whole cent; each line also records its `vehicle_id`, `subscription_id`, `tier_rate_cents`, `surcharge_cents`, and `billable_days`, and lines are emitted in subscription creation order, earliest created first. The invoice's `gross_cents` is the plain sum of the rounded line nets.

Credits settle against the gross before anything is billed. `credit_applied_cents` is the smaller of the carrier's `credit_balance_cents` and the gross; when positive, a negative ledger entry of that amount with reason `INVOICE_CREDIT_APPLICATION` is appended per §2.8, and `amount_due_cents` is the gross minus the applied credit. The invoice's `due_date` falls on the fifteenth day of the month after the period — the first day of the following month plus fourteen days, so an August 2026 period falls due on 2026-09-15. The invoice is stamped `issued_at` and opens as `ISSUED`, with `status`, `tier_applied`, `lines`, and `billed_line_count` all persisted; when the amount due works out to zero — whether because credit covered the gross in full or because nothing was billable — the invoice is born `PAID` instead. After the computation, the close resets pause bookkeeping on all of the carrier's subscriptions — `paused_days_current_period` returns to zero while a still-paused row keeps its `paused_at` — appends the period label — a zero-padded `YYYY-MM` string such as `2026-08` — to `closed_billing_periods`, runs the past-due sweep for the carrier, and increments the carrier's `version` by one. The close returns the created invoice.

Payment is exact. A `FinanceAdmin` records payment by submitting `amount_cents`, and the amount must equal the invoice's `amount_due_cents` to the cent — partial payments and overpayments are both rejected with `ERR_PAYMENT_AMOUNT_MISMATCH` (HTTP 400) — and the invoice must still be payable, with a payment attempted against an already-`PAID` invoice rejected as `ERR_INVOICE_NOT_PAYABLE` (HTTP 409); per §2.10, the amount check outranks the payable check when both would fail. A successful payment moves the invoice from `ISSUED` or `PAST_DUE` to `PAID`, and `PAID` is terminal. Time moves the other way: the past-due sweep — run at every clock-set and at every billing close — flips an `ISSUED` invoice to `PAST_DUE` once its `due_date` lies in the past, and that flip propagates `payment_standing` `PAST_DUE` onto the carrier's `SCHEDULED`, `ACTIVE`, and `PAUSED` subscriptions, which in turn blocks new subscriptions and credential activation per §3.4. When the last past-due invoice is settled — by payment or by the dispute credit sweep of §3.6 — standing returns to `CURRENT`.

Two read models serve planning and oversight. The invoice preview answers "what would this period cost" without persisting anything: it defaults each of `period_year` and `period_month` independently to the current period's value when omitted — a supplied value that is not an integer, or a `period_month` outside 1–12, is rejected with `ERR_INVALID_REQUEST` (HTTP 400) — uses the same line, tier, surcharge, and half-up rounding math as a real close, but projects billable days forward — an `ACTIVE` subscription bills from the later of its start and the period start through the earlier of its end and the period end, minus paused days accrued to date; a `PAUSED` subscription bills only its overlap up to `paused_at`, assuming it stays paused; a `SCHEDULED` subscription whose start date falls inside the period bills from that start through the earlier of its end and the period end; an already-`CLOSED` subscription whose (possibly pulled-back) window still overlaps the period contributes a line as well, billing its realized window minus its accumulated paused days. The tier comes from the projected line count, `credit_applied_cents` reports the credit that would apply given the current balance without applying it, and the preview returns `lines`, `billed_line_count`, `tier_applied`, `gross_cents`, `credit_applied_cents`, `amount_due_cents`, and the period. Preview and close diverge whenever pauses or activations land between the preview day and period end.

The ROI report quantifies the program for a carrier and period; `period_year` and `period_month` are both required query parameters — unlike the preview, there is no current-period default — and a `variant` value outside `STANDARD` and `CONSERVATIVE` is rejected with `ERR_INVALID_REQUEST` (HTTP 400). It buckets the carrier's bypass events by the month of `approach_at` and reports `total_approaches`, `bypasses_granted`, and `pull_ins` — the three partition, so approaches equal grants plus pull-ins — along with `verified_bypasses`, the granted events whose `weight_verified` and `credentials_complete` are both true. `bypass_rate_bps` is the granted count multiplied by ten thousand and divided by the total, fractional part discarded, and zero when the month saw no approaches. The `variant` parameter picks the savings basis: `STANDARD`, the default, counts every granted bypass as an avoided inspection, while `CONSERVATIVE` counts only verified bypasses and therefore reports savings no higher than standard on identical data whenever any grant went unverified. `estimated_savings_cents` multiplies the counted bypasses by 1,275 cents, the avoided cost per bypass. `subscription_fees_cents` is the `gross_cents` of the carrier's invoice for the period, or zero when none exists. `roi_bps` is the estimated savings minus the fees, multiplied by ten thousand, divided by the fees, and rounded half-up (a quotient that is negative at an exact half rounds away from zero) — and it is null when the fees are zero. `inspections_recorded` counts the carrier's inspection reports dated within the month, and `inspection_reduction_bps` equals the bypass rate: every bypass is an avoided inspection.

Inspection records themselves arrive through the `SafetyDataFeed`, each naming `carrier_id`, `vehicle_id`, an `inspection_level` of `LEVEL_1`, `LEVEL_2`, or `LEVEL_3`, the `inspected_at` instant — never in the future, else `ERR_FUTURE_INSPECTION` (HTTP 400) — a `violations_found` count of zero or more, and an `out_of_service_order` flag defaulting to false. These reports feed nothing but the ROI report; they alter no state elsewhere.

## 4. Endpoint Definitions

Operations that create a new resource — onboarding a carrier, registering a config, station, vehicle, credential, subscription, dispute, override, snapshot, event, or inspection report, and closing a billing period (which creates the invoice) — return `201 Created`. Operations that modify an existing resource, drive a lifecycle transition, record a payment, or advance the logical clock return `200 OK`. Request and response payloads are as narrated in §3; the table below is the routing contract only. Rows marked "Any authenticated role" admit every role declared in §2.1.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/api/_clock/set_current_utc` | Advance the logical clock and run the materialization sweep | PlatformAdmin |
| POST | `/api/carriers` | Onboard a carrier (ENROLLED, posture NOT_EVALUATED) | PlatformAdmin |
| GET | `/api/carriers/{carrierId}` | Get one carrier with posture, credit ledger, closed periods, and version | Any authenticated role |
| POST | `/api/carriers/{carrierId}/transition` | Lifecycle transition: ACTIVE or SUSPENDED (ComplianceOfficer), TERMINATED (PlatformAdmin) | ComplianceOfficer, PlatformAdmin |
| POST | `/api/carriers/{carrierId}/close-billing-period` | Close a fully elapsed month and issue the invoice | FinanceAdmin |
| GET | `/api/carriers/{carrierId}/invoice-preview` | Provisional forward-looking invoice projection for a period (defaults to current) | Any authenticated role |
| GET | `/api/carriers/{carrierId}/roi-report` | Inspection-reduction and ROI report for a period | Any authenticated role |
| POST | `/api/state-program-configs` | Create a per-state rules config (starts PILOT) | StateProgramManager |
| GET | `/api/state-program-configs/{configId}` | Get one state config, including its current version | Any authenticated role |
| PATCH | `/api/state-program-configs/{configId}` | Patch rule fields and/or participation status (OCC) | StateProgramManager |
| POST | `/api/stations` | Register a weigh station under a state config | StateProgramManager |
| GET | `/api/stations` | List stations | Any authenticated role |
| GET | `/api/stations/{stationId}` | Get one station | Any authenticated role |
| PATCH | `/api/stations/{stationId}` | Transition station operational status | StateProgramManager |
| POST | `/api/vehicles` | Register a vehicle for a carrier | CarrierManager |
| GET | `/api/vehicles` | List vehicles | Any authenticated role |
| GET | `/api/vehicles/{vehicleId}` | Get one vehicle | Any authenticated role |
| PATCH | `/api/vehicles/{vehicleId}` | Transition service status (retirement cascades) | CarrierManager |
| POST | `/api/bypass-credentials` | Provision a transponder or app credential for a vehicle | CarrierManager |
| GET | `/api/bypass-credentials` | List credentials | Any authenticated role |
| GET | `/api/bypass-credentials/{credentialId}` | Get one credential | Any authenticated role |
| POST | `/api/bypass-credentials/{credentialId}/transition` | Credential lifecycle: activate, suspend, deactivate | CarrierManager |
| POST | `/api/safety-score-snapshots` | Post a safety-score snapshot (OCC on the carrier) | SafetyDataFeed |
| GET | `/api/safety-score-snapshots` | List snapshots | Any authenticated role |
| GET | `/api/safety-score-snapshots/{snapshotId}` | Get one snapshot | Any authenticated role |
| POST | `/api/bypass-events` | Record a roadside approach and its computed decision | TelematicsGateway |
| GET | `/api/bypass-events` | List bypass events | Any authenticated role |
| GET | `/api/bypass-events/{eventId}` | Get one bypass event (immutable record) | Any authenticated role |
| POST | `/api/bypass-disputes` | Open a dispute on a PULL_IN event | CarrierManager |
| GET | `/api/bypass-disputes` | List disputes | Any authenticated role |
| GET | `/api/bypass-disputes/{disputeId}` | Get one dispute | Any authenticated role |
| POST | `/api/bypass-disputes/{disputeId}/adjudicate` | Officer decision from OPENED or APPEALED | ComplianceOfficer |
| POST | `/api/bypass-disputes/{disputeId}/appeal` | Appeal an UPHELD dispute | CarrierManager |
| POST | `/api/eligibility-overrides` | Request a temporary eligibility waiver (OCC on the carrier) | CarrierManager |
| GET | `/api/eligibility-overrides` | List eligibility overrides | Any authenticated role |
| GET | `/api/eligibility-overrides/{overrideId}` | Get one override | Any authenticated role |
| POST | `/api/eligibility-overrides/{overrideId}/decide` | Approve, reject, or revoke an override | ComplianceOfficer |
| POST | `/api/vehicle-subscriptions` | Subscribe a vehicle | CarrierManager |
| GET | `/api/vehicle-subscriptions` | List subscriptions | Any authenticated role |
| GET | `/api/vehicle-subscriptions/{subscriptionId}` | Get one subscription, including pause counters | Any authenticated role |
| POST | `/api/vehicle-subscriptions/{subscriptionId}/cancel` | Cancel a subscription immediately | CarrierManager |
| GET | `/api/invoices` | List invoices | Any authenticated role |
| GET | `/api/invoices/{invoiceId}` | Get one invoice with its lines | Any authenticated role |
| POST | `/api/invoices/{invoiceId}/record-payment` | Record full payment of the amount due | FinanceAdmin |
| POST | `/api/inspection-reports` | Post a roadside inspection record | SafetyDataFeed |
| GET | `/api/inspection-reports` | List inspection reports | Any authenticated role |
| GET | `/api/inspection-reports/{reportId}` | Get one inspection report | Any authenticated role |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in the narratives of §2 and §3; this catalogue is the identifier-to-status contract only.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_CARRIER_OWNERSHIP_MISMATCH` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ISS_SCORE` | 400 Bad Request |
| `ERR_CREDIT_AMOUNT_OUT_OF_RANGE` | 400 Bad Request |
| `ERR_INVALID_DATE_RANGE` | 400 Bad Request |
| `ERR_FUTURE_APPROACH` | 400 Bad Request |
| `ERR_STALE_APPROACH` | 422 Unprocessable Entity |
| `ERR_FUTURE_INSPECTION` | 400 Bad Request |
| `ERR_CARRIER_NOT_FOUND` | 404 Not Found |
| `ERR_STATE_PROGRAM_CONFIG_NOT_FOUND` | 404 Not Found |
| `ERR_STATION_NOT_FOUND` | 404 Not Found |
| `ERR_VEHICLE_NOT_FOUND` | 404 Not Found |
| `ERR_CREDENTIAL_NOT_FOUND` | 404 Not Found |
| `ERR_BYPASS_EVENT_NOT_FOUND` | 404 Not Found |
| `ERR_DISPUTE_NOT_FOUND` | 404 Not Found |
| `ERR_OVERRIDE_NOT_FOUND` | 404 Not Found |
| `ERR_SUBSCRIPTION_NOT_FOUND` | 404 Not Found |
| `ERR_INVOICE_NOT_FOUND` | 404 Not Found |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_CARRIER_NOT_ACTIVE` | 409 Conflict |
| `ERR_CARRIER_INELIGIBLE_FOR_APPROVAL` | 422 Unprocessable Entity |
| `ERR_CARRIER_STILL_INELIGIBLE` | 422 Unprocessable Entity |
| `ERR_CARRIER_NOT_BYPASS_ELIGIBLE` | 422 Unprocessable Entity |
| `ERR_VEHICLE_NOT_IN_SERVICE` | 409 Conflict |
| `ERR_NO_SAFETY_SNAPSHOT` | 422 Unprocessable Entity |
| `ERR_OVERRIDE_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_SUBSCRIPTION_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_EVENT_NOT_DISPUTABLE` | 422 Unprocessable Entity |
| `ERR_DISPUTE_WINDOW_EXPIRED` | 422 Unprocessable Entity |
| `ERR_DISPUTE_ALREADY_OPEN` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES` | 403 Forbidden |
| `ERR_DUPLICATE_DOT_NUMBER` | 409 Conflict |
| `ERR_DUPLICATE_VIN` | 409 Conflict |
| `ERR_DUPLICATE_DEVICE_SERIAL` | 409 Conflict |
| `ERR_DUPLICATE_STATE_CONFIG` | 409 Conflict |
| `ERR_DUPLICATE_STATION_CODE` | 409 Conflict |
| `ERR_DUPLICATE_BYPASS_EVENT` | 409 Conflict |
| `ERR_CREDENTIAL_TYPE_ALREADY_ACTIVE` | 409 Conflict |
| `ERR_NO_ACTIVE_SUBSCRIPTION` | 402 Payment Required |
| `ERR_CARRIER_PAST_DUE` | 402 Payment Required |
| `ERR_PAYMENT_AMOUNT_MISMATCH` | 400 Bad Request |
| `ERR_INVOICE_NOT_PAYABLE` | 409 Conflict |
| `ERR_BILLING_PERIOD_ALREADY_CLOSED` | 409 Conflict |
| `ERR_BILLING_PERIOD_NOT_CLOSABLE` | 422 Unprocessable Entity |
