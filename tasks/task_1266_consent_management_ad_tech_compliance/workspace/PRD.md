# Consent Management & Ad Tech Compliance API — Product Requirements Document

## 1. Introduction

Digital marketing operations live under a tightening mesh of privacy regimes: GDPR-style opt-in jurisdictions, California-style opt-out regimes with binding Global Privacy Control signals, children's-data age gates, and regulators who arrive with deadline-bearing sweeps and expect proof, not promises. The privacy team inside an ad-tech organization therefore needs more than a consent banner — it needs a system of record that can prove, per visitor and per purpose, what was consented to, under which policy version, with which downstream vendors notified, and what happened when an auditor went looking for unauthorized trackers.

This document specifies a Consent Management & Ad Tech Compliance API for that team. The platform administers web **Properties** and their jurisdiction-specific privacy policies, configures and publishes consent banners, maintains a registry of ad-tech **Vendors** and the tag rules that fire them, records visitor consent and opt-out signals with retention-aware proof, processes do-not-sell/share requests all the way to vendor-level acknowledgements, runs tag audit scans that detect unauthorized trackers, and responds to regulatory sweeps under deadline pressure — including a property-wide compliance freeze when a sweep escalates. All behaviour is evaluated against a deterministic logical clock so that retention expiries, age boundaries, and sweep deadlines are reproducible.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a set of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes six roles: `PrivacyAdmin`, `VendorManager`, `ComplianceAuditor`, `Visitor`, `Anonymous`, and `Any`. Requests missing either header, or carrying an unrecognized role, are rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (400). Access to specific operations is restricted by role per the endpoint table in §4; an attempt to perform an action outside the caller's designated role is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (403).

Role identities work as follows. When `X-User-Role` is `Visitor`, `X-User-ID` is the `id` of the acting `VisitorProfile`; every visitor-scoped mutation (age attestation, GPC signals, consent records, do-not-sell requests, withdrawals and re-grants) compares the target visitor's `id` to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNERSHIP` (403). When `X-User-Role` is `PrivacyAdmin`, `VendorManager`, or `ComplianceAuditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where an audit rule requires (for example, as `created_by_user_id` on a `TagAuditScan` or `confirmed_by_user_id` on a `TrackerFinding`) but never compares it to any entity's `id`. When `X-User-Role` is `Anonymous`, the caller is unauthenticated and may only register new visitor profiles; `X-User-ID` is an opaque label. `Any` denotes that every authenticated role may perform the operation (used for read endpoints); ownership is not enforced on reads — reads are open to any authenticated caller.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order. Resource `id` values are identifiers only and are never used for ordering, ranking, selection, or tie-breaking anywhere in the system.

Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`. List endpoints additionally accept the filter parameters named in §3 narratives (for example `property_id`, `status`, `jurisdiction_code`, `vendor_id`, `banner_config_id`, `purpose_category`, `verification_status`, `propagation_status`).

### 2.4. The Logical Clock and Lazy Compliance Evaluation

All time-dependent behaviour — age gating, retention expiry, scan scheduling, sweep deadlines — is evaluated against a single logical clock, never against the server's wall clock. At startup the logical clock reads exactly `2026-05-01T00:00:00Z`. A `PrivacyAdmin`-only test-driving capability advances the clock to a supplied `to_iso8601` instant and returns the resulting `current_utc`. Two compliance effects are evaluated lazily, meaning they are applied whenever the affected resource is read or written, and whenever the clock is set: a consent record whose pinned retention horizon has been reached transitions to `EXPIRED`, and a regulatory sweep whose response deadline has passed transitions to `ESCALATED` with its full escalation cascade (see §3.8).

### 2.5. Common Resource Properties

All primary resources carry a standard set of system-managed fields:

- **`id` (string):** a unique, server-minted UUID with no type prefix (for example `8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2`). Clients supplying `id` or `version` inside creation payloads are ignored — the server mints its own.
- **`created_at` (string):** an ISO 8601 UTC timestamp with three fractional digits, taken from the logical clock.
- **`updated_at` (string):** refreshed on every mutation, including mutations caused by cascade side effects originating on other resources.
- **`version` (integer):** starts at 1 and increments by one on every mutation of that resource.

One entity is deliberately immutable: a `GpcSignalEvent` is an append-only record carrying only `id`, `created_at`, `visitor_id`, and `signal`; it has neither `updated_at` nor `version`, and no endpoint modifies or deletes it.

### 2.6. Property Posture: The Compliance Freeze

Every Property carries a computed `posture`, either `NORMAL` or `FROZEN`. The property is `FROZEN` while any of its regulatory sweeps is in `ESCALATED` status, and `NORMAL` otherwise. The freeze gates administrative and consent-acquisition mutations: while `FROZEN`, policy activation/retirement/amendment, banner configuration creation, publication, and archival, vendor registration, approval, and suspension, tag rule creation and status changes, and consent grant or re-grant are all rejected with `ERR_PROPERTY_FROZEN` (409). Rights-honouring operations are never frozen: consent withdrawal, do-not-sell submission, sweep handling itself, audit scans and finding adjudication, and all reads proceed normally. When the last `ESCALATED` sweep of the property is closed, the posture returns to `NORMAL`; banner configs that were suppressed by the freeze are not automatically re-published (see §3.2).

### 2.7. Optimistic Concurrency on Banner Publication

Exactly one endpoint participates in optimistic concurrency control: publishing a banner configuration. Because publication supersedes whichever configuration is currently published for the same property and jurisdiction, the publish request must carry `expected_property_version` equal to the property's current `version` as last observed by the client. If the property's version has advanced since — whether through another publication, a consent cascade, or a posture flip — the request is rejected with `ERR_STALE_PROPERTY_VERSION` (HTTP 412). A successful publication increments the property's `version` by exactly one. No other endpoint accepts a version field.

### 2.8. Validation Discipline and Priority Order

Every request is validated against an ordered ladder, and the first failing rung determines the error returned when several rules are violated at once:

1. **Authentication** — presence and validity of `X-User-ID` and `X-User-Role` (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`).
2. **Authorization** — the role is permitted the operation (`ERR_INSUFFICIENT_PERMISSIONS`); for `Visitor` callers, ownership of the targeted visitor (`ERR_FORBIDDEN_OWNERSHIP`).
3. **Existence** — every identifier referenced by the path or body must exist, checked left to right, surfacing the resource-specific not-found error (`ERR_PROPERTY_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_BANNER_CONFIG_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`, `ERR_TAG_RULE_NOT_FOUND`, `ERR_VISITOR_NOT_FOUND`, `ERR_CONSENT_RECORD_NOT_FOUND`, `ERR_DNS_REQUEST_NOT_FOUND`, `ERR_PROPAGATION_NOT_FOUND`, `ERR_SCAN_NOT_FOUND`, `ERR_FINDING_NOT_FOUND`, `ERR_SWEEP_NOT_FOUND`).
4. **Stale-version check** — only on banner publication (`ERR_STALE_PROPERTY_VERSION`), evaluated before all state and business rules.
5. **Posture gate** — the property must be `NORMAL` for frozen-gated operations (`ERR_PROPERTY_FROZEN`). This rung outranks every business rule below it: for example, a child visitor's grant attempt on a frozen property fails with `ERR_PROPERTY_FROZEN`, not `ERR_CHILD_CONSENT_FORBIDDEN`.
6. **Transition preconditions** — the target resource must be in a state from which the requested transition exists (`ERR_POLICY_INVALID_TRANSITION`, `ERR_BANNER_CONFIG_NOT_PUBLISHABLE`, `ERR_VENDOR_INVALID_TRANSITION`, `ERR_TAG_RULE_INVALID_TRANSITION`, `ERR_CONSENT_INVALID_TRANSITION`, `ERR_DNS_INVALID_STATE`, `ERR_PROPAGATION_INVALID_STATE`, `ERR_SCAN_NOT_RUNNABLE`, `ERR_FINDING_INVALID_STATE`, `ERR_SWEEP_INVALID_STATE`, `ERR_SWEEP_DEADLINE_PASSED`).
7. **Safety — age verification** — consent grant or re-grant requires a completed age attestation (`ERR_AGE_UNVERIFIED`).
8. **Safety — child protection** — a `CHILD` visitor may only be granted the `NECESSARY` purpose (`ERR_CHILD_CONSENT_FORBIDDEN`, 403).
9. **Referential — active policy** — an `ACTIVE` jurisdiction policy must exist for the applicable `jurisdiction_code` (`ERR_NO_ACTIVE_POLICY`).
10. **Referential — same-property linkage** — a tag rule's vendor and banner configuration must belong to the same property (`ERR_CROSS_PROPERTY_REFERENCE`); the vendor must additionally be `APPROVED` (`ERR_VENDOR_NOT_APPROVED`). The cross-property check outranks the uniqueness constraint below: a tag-rule creation that references a foreign-property vendor while duplicating an existing (configuration, purpose) pair fails with `ERR_CROSS_PROPERTY_REFERENCE`, not `ERR_DUPLICATE_TAG_RULE`.
11. **Temporal — coverage window** — the logical clock must fall inside the active policy's coverage window (`ERR_POLICY_OUTSIDE_COVERAGE_WINDOW`).
12. **Temporal — scan cooldown** — a new scan's window, expanded by the cooldown buffer, must not intersect any existing scan's window on the same property (`ERR_SCAN_WINDOW_CONFLICT`).
13. **Constraint — policy window overlap** (`ERR_POLICY_WINDOW_OVERLAP`), **tag-rule uniqueness** (`ERR_DUPLICATE_TAG_RULE`), **consent-purpose uniqueness** (`ERR_DUPLICATE_CONSENT_PURPOSE`), and **do-not-sell applicability** (`ERR_DNS_NOT_APPLICABLE`).
14. **Segregation of duties** — the auditor who created a scan may not confirm violations on it (`ERR_SEGREGATION_OF_DUTIES_VIOLATION`, 403).

Malformed payloads — missing required fields, type mismatches, enum values outside the declared sets — are rejected with `ERR_INVALID_REQUEST` (400).

### 2.9. Penalty Money and Rounding Discipline

Regulatory exposure is computed in integer cents. Where a per-finding formula produces fractional cents, each finding's amount is rounded half-up to whole cents **first**, and the rounded per-finding amounts are **then summed** into the sweep total. Summing raw amounts and rounding once at the end is a different, incorrect procedure and yields different totals. Datetimes are compared at second precision, and day arithmetic adds whole days.

### 2.10. Consent Proof and Retention Principles

Consent records are the legal proof artifact. Every transition into `GRANTED` snapshots the governing policy's `retention_days` into `policy_snapshot_retention_days` and stamps `last_changed_at`; two expiry horizons are then maintained: `expires_at_pinned` (computed from the snapshot; authoritative — it alone drives the `EXPIRED` transition) and `expires_at_rolling` (recomputed on read from the live policy's current `retention_days`, for audit comparison). When the privacy team amends a policy's retention horizon, existing records keep their pinned horizon while their rolling horizon moves — the two values intentionally diverge, and the record's lifecycle follows the pinned one.

## 3. Business Logic & Workflows

### 3.1. Properties and Jurisdiction Policies

A `PrivacyAdmin` onboards a digital property by registering it with a `name` and a `sale_share_designation` declaring the property's data-sale posture: `SELLS_AND_SHARES`, `SHARES_ONLY`, or `NO_SALE_NO_SHARE`. The designation is not decorative — a property designated `NO_SALE_NO_SHARE` categorically rejects do-not-sell requests with `ERR_DNS_NOT_APPLICABLE`, because there is nothing to opt out of. New properties begin with `posture` `NORMAL` and a `granted_purpose_count` of zero.

Each property is then governed per jurisdiction through **JurisdictionPolicy** resources, created by a `PrivacyAdmin` with a `jurisdiction_code` (for example `EU-GDPR`, `US-CA`, `BR-LGPD`), a `banner_regime` of `OPT_IN_REQUIRED`, `OPT_OUT_ALLOWED`, or `NOTICE_ONLY`, a `min_consent_age`, a `retention_days` horizon of at least one day, a `gpc_honored` flag, and a coverage window from `effective_from` (inclusive) to `effective_to` (exclusive; omitting it leaves the window open-ended). A policy begins `DRAFT`; a `PrivacyAdmin` activates it and later retires it through status updates (`DRAFT → ACTIVE → RETIRED`, each step via the policy update operation; attempting `RETIRED` directly from `DRAFT` fails with `ERR_POLICY_INVALID_TRANSITION`). While `ACTIVE`, a policy's `retention_days` may be amended in the same update operation, which moves the rolling expiry horizon of every consent record under it (§2.10).

Activation enforces a hard coverage rule for the property's jurisdiction: the half-open windows of `ACTIVE` policies sharing a `jurisdiction_code` must never intersect. Adjacency is explicitly permitted — a successor policy whose `effective_from` equals the predecessor's `effective_to` activates cleanly, while a start even one day earlier collides and is rejected with `ERR_POLICY_WINDOW_OVERLAP`. Retiring a policy does not disturb consent records already granted under it (their pinned retention horizon survives), but with no `ACTIVE` policy left for the jurisdiction, new consent grants fail with `ERR_NO_ACTIVE_POLICY`.

### 3.2. Banner Configuration and Publication

Consent banners are versioned through **ConsentBannerConfig** resources. A `PrivacyAdmin` drafts a configuration with the target `jurisdiction_code`, the `categories_shown` (a subset of `ANALYTICS`, `ADVERTISING`, `SALE_SHARE`), and a human-readable `config_label`. The configuration lifecycle is `DRAFT → PUBLISHED → SUPERSEDED | SUPPRESSED | ARCHIVED`, with `DRAFT → ARCHIVED` as a cleanup path and `SUPPRESSED → PUBLISHED` as the recovery path after a freeze lifts.

Publication is the property's commit point and is guarded by the optimistic concurrency contract of §2.7: the request must carry `expected_property_version`. Beyond the stale-version rejection, publication requires the property to be `NORMAL`, the configuration to be in `DRAFT` or `SUPPRESSED` (otherwise `ERR_BANNER_CONFIG_NOT_PUBLISHABLE`), an `ACTIVE` policy to exist for the configuration's jurisdiction (`ERR_NO_ACTIVE_POLICY`), and the logical clock to fall inside that policy's coverage window (`ERR_POLICY_OUTSIDE_COVERAGE_WINDOW`). On success the publication stamps `published_at`, increments the property's `version` by one, and supersedes whichever configuration was previously `PUBLISHED` for the same property and jurisdiction: the old configuration moves to `SUPERSEDED` and every `ENABLED` tag rule bound to it drops to `DISABLED`. Archival applies only to `DRAFT` configurations; archiving a published one, or publishing an archived one, is rejected with `ERR_BANNER_CONFIG_NOT_PUBLISHABLE`.

While a property is `FROZEN`, the freeze cascade pushes each `PUBLISHED` configuration to `SUPPRESSED`. Once the freeze lifts, a `PrivacyAdmin` re-publishes the suppressed configuration through the same publication operation (the `SUPPRESSED → PUBLISHED` transition), again carrying the property's fresh version.

### 3.3. Vendor Registry and Tag Governance

The ad-tech supply side is administered by the `VendorManager`, who registers each **Vendor** with a `legal_name`, the `declared_purposes` it serves (a subset of `ANALYTICS`, `ADVERTISING`, `SALE_SHARE`), and its declared `tracker_signatures`. A vendor begins `PENDING_REVIEW`; only a `PrivacyAdmin` may approve it (`PENDING_REVIEW → APPROVED`) or later suspend it (`APPROVED → SUSPENDED`). Both actions require the vendor to be in the appropriate source state (`ERR_VENDOR_INVALID_TRANSITION` otherwise), and `SUSPENDED` is terminal — there is no path back.

**TagRule** resources wire a vendor to a purpose under a banner configuration. The `VendorManager` creates one by naming the `vendor_id`, the `banner_config_id`, and the `purpose_category`; the rule inherits its `property_id` from the banner configuration's property. Creation enforces, in this order relative to other checks: the vendor and the configuration must live on the same property (`ERR_CROSS_PROPERTY_REFERENCE`), the vendor must be `APPROVED` (`ERR_VENDOR_NOT_APPROVED`), and the pair (`banner_config_id`, `purpose_category`) must be unique (`ERR_DUPLICATE_TAG_RULE`). A new rule starts `ENABLED`. The `VendorManager` toggles it between `ENABLED` and `DISABLED` (a genuine cycle — rules are routinely paused and resumed) and may retire it from either state; `RETIRED` is terminal, and any transition not present in the machine is rejected with `ERR_TAG_RULE_INVALID_TRANSITION`. Re-enabling a `DISABLED` rule re-checks the vendor's standing: if the vendor has since been suspended, the enable fails with `ERR_VENDOR_NOT_APPROVED`.

Suspending a vendor is deliberately blunt: every `ENABLED` tag rule of that vendor cascades to `DISABLED`, so a flagged partner goes dark across all banner configurations at once. Reads stay open — tag rules can be listed for a property, or filtered by `vendor_id`, `banner_config_id`, or `status`.

### 3.4. Visitor Registration, Age Gating, and Global Privacy Control

Visitors arrive anonymously: registration (the only `Anonymous`-permitted operation) creates a `VisitorProfile` from the `property_id`, an `external_ref` pseudonymous reference, and the visitor's `jurisdiction_code`. An `attested_birthdate` may be supplied at registration, but doing so only stores the value — the age gate is not evaluated until the visitor explicitly completes the age-attestation step. A fresh profile carries `age_status` `UNVERIFIED`, `gpc_effective` `UNSET`, and `sale_share_opted_out` false.

Age attestation is a self-service act by the `Visitor` (ownership enforced per §2.1) carrying an `attested_birthdate`. It requires an `ACTIVE` policy for the visitor's jurisdiction (`ERR_NO_ACTIVE_POLICY`) and resolves `age_status` as follows: the visitor is `ADULT` when the date that is exactly `min_consent_age` years after the attested birthdate is on or before the current logical-clock date — a visitor whose qualifying birthday is today passes — and `CHILD` otherwise. A `CHILD` visitor may grant only the `NECESSARY` purpose; any other purpose is refused with `ERR_CHILD_CONSENT_FORBIDDEN`.

Global Privacy Control is honored as an auditable event stream. Each signal a `Visitor` sends with a `signal` of `ON` or `OFF` is persisted as an immutable `GpcSignalEvent` and advances the profile's `gpc_effective` and `gpc_updated_at`. When the signal is `ON` and the visitor's active policy has `gpc_honored` true, the profile's `sale_share_opted_out` becomes true and the honoring cascade fires: the flag flip itself drives every `GRANTED` consent record the visitor holds for `SALE_SHARE` into `WITHDRAWN` with `source_of_decision` `AUTO_GPC_WITHDRAW` (records for other purposes are untouched), and each such withdrawal decrements the property's `granted_purpose_count` and refreshes its `version`. Setting the signal `OFF` clears `sale_share_opted_out` but never resurrects cascaded withdrawals — a withdrawn record stays `WITHDRAWN` until the visitor deliberately re-grants it.

### 3.5. Consent Records and Preference Resolution

Consent is recorded per visitor and purpose through the grant operation, which a `Visitor` performs with a `purpose_category` of `NECESSARY`, `ANALYTICS`, `ADVERTISING`, or `SALE_SHARE`. The grant path enforces the full validation ladder of §2.8: property not frozen, an attested (non-`UNVERIFIED`) age status (`ERR_AGE_UNVERIFIED`), the child-purpose restriction, an `ACTIVE` policy for the visitor's jurisdiction (`ERR_NO_ACTIVE_POLICY`), the clock inside the policy's coverage window (`ERR_POLICY_OUTSIDE_COVERAGE_WINDOW`), and purpose uniqueness — a visitor may hold only one record per purpose in `GRANTED` or `WITHDRAWN`, so a duplicate grant is rejected with `ERR_DUPLICATE_CONSENT_PURPOSE`. Once a record has reached `EXPIRED`, however, the gate releases and a fresh grant for the same purpose creates a new record.

A consent record is born `GRANTED`, stamped with the currently `PUBLISHED` banner configuration for the visitor's jurisdiction in `banner_config_id` (null when none is published), the policy snapshot, and `source_of_decision` `EXPLICIT_GRANT`. Its lifecycle is deliberately cyclic: `GRANTED → WITHDRAWN → GRANTED` and around again. Withdrawal requires `GRANTED` and works even while the property is frozen; re-grant requires `WITHDRAWN` and re-applies the grant-time gates (posture, age, child, policy, window), refreshing the policy snapshot, the banner binding, and the timestamps. Both operations keep `source_of_decision` truthful (`EXPLICIT_WITHDRAW`, `EXPLICIT_GRANT`). Attempting a withdrawal on an already-withdrawn record, or a re-grant on a granted one, fails with `ERR_CONSENT_INVALID_TRANSITION`. Independently, the retention rule of §2.10 moves any record — granted or withdrawn — to terminal `EXPIRED` once the logical clock reaches `expires_at_pinned`; the expiry instant itself counts (a record is alive one second before its horizon and `EXPIRED` exactly at it), and expiry flips `source_of_decision` to `EXPIRY`.

The property's `granted_purpose_count` is a living ledger: it always equals the number of consent records in `GRANTED` status across all of the property's visitors. Grants and re-grants increment it; withdrawals and expiries decrement it; a grant-then-withdraw pair nets to zero; and every such adjustment also increments the property's `version`. An auditor can always reconcile the stored counter against a filtered listing of the property's consent records.

The same rules power a non-persisting **consent preview** read: given a visitor and a `purpose_category`, it evaluates the effective decision without writing anything, returning a `decision` token. The evaluation is a strict waterfall. First, a `CHILD` visitor asking for anything other than `NECESSARY` yields `BLOCKED_CHILD`. Second, `NECESSARY` always yields `ALWAYS_GRANTED`. Third, for `SALE_SHARE` under a `gpc_honored` policy with the signal `ON`, the signal wins unless the visitor re-granted after the signal arrived: when the record is `GRANTED` and its `last_changed_at` is strictly later than `gpc_updated_at`, the decision is `EXPLICIT_GRANT`; otherwise it is `FORCED_OPT_OUT`. Fourth, an existing `GRANTED` record yields `EXPLICIT_GRANT` and a `WITHDRAWN` one `EXPLICIT_WITHDRAWN`; an `EXPIRED` record is treated as absent. Finally the regime default applies: `OPT_IN_REQUIRED` yields `DENIED_BY_DEFAULT`, while `OPT_OUT_ALLOWED` and `NOTICE_ONLY` yield `GRANTED_BY_DEFAULT`.

### 3.6. Do-Not-Sell Processing and Vendor Propagation

A `Visitor` files a do-not-sell/share request against their own profile, optionally narrowing `scope_categories` (defaulting to `SALE_SHARE` alone). Filing presupposes the property actually sells or shares data (§3.1). Each request carries two independent state dimensions. The verification dimension (`verification_status`) is settled by a `PrivacyAdmin`: `UNVERIFIED → VERIFIED` or `UNVERIFIED → REJECTED`, and any attempt to re-settle a settled request fails with `ERR_DNS_INVALID_STATE`. The propagation dimension (`propagation_status`) tracks downstream notification: `NOT_STARTED → PROPAGATING → ALL_CONFIRMED | PARTIAL_FAILURE`, with `PARTIAL_FAILURE → PROPAGATING` when the team re-dispatches after fixing a failed partner.

Propagation is launched by a `PrivacyAdmin` and requires `VERIFIED` with propagation in `NOT_STARTED` or `PARTIAL_FAILURE` (anything else is `ERR_DNS_INVALID_STATE`). The dispatch computes the in-scope vendors — those `APPROVED` vendors of the property whose `declared_purposes` intersect the request's scope, taken in registration order — and creates one `VendorPropagation` per vendor, each bound to the request through its `request_id` and starting `PENDING` with `attempts` one and a `last_attempt_at` stamp. On a re-dispatch, vendors already holding a `PENDING` or `CONFIRMED` propagation on the request are skipped. If no vendor is in scope, the request jumps straight to `ALL_CONFIRMED` with `total_propagations` zero.

Each propagation is settled by the `VendorManager`: `PENDING → CONFIRMED` or `PENDING → FAILED`, and a failed delivery is retried via `FAILED → PENDING`, which increments `attempts` and re-stamps `last_attempt_at`. Settling a `CONFIRMED` propagation again, or retrying a `PENDING` one, is `ERR_PROPAGATION_INVALID_STATE`. The request maintains four counters — `total_propagations`, `pending_count`, `confirmed_count`, `failed_count` — and an iron invariant: the three status counters always sum to `total_propagations`, which always equals the number of propagation children. While any child is `PENDING` the request remains `PROPAGATING`; when none is pending it settles to `ALL_CONFIRMED` if there are no failures and `PARTIAL_FAILURE` otherwise.

### 3.7. Tag Audit Scans and Finding Adjudication

The privacy team proves diligence through scheduled **TagAuditScan** operations. A `ComplianceAuditor` schedules a scan with a `scheduled_start` and a `duration_minutes` length. Scan windows on the same property respect a two-hour cooldown moat: the new window, expanded by one hundred and twenty minutes on both sides, must not intersect any existing scan's raw window — a scan starting exactly one hundred and twenty minutes after the previous scan's end is allowed, one minute earlier is not, and violations are rejected with `ERR_SCAN_WINDOW_CONFLICT`. (Note the contrast with policy windows in §3.1: policies use plain half-open adjacency with no buffer.)

Running the scan (again `ComplianceAuditor`-only, and only from `SCHEDULED`, else `ERR_SCAN_NOT_RUNNABLE`) feeds the system the `observed_trackers` — each with a `tracker_signature` and the `purpose_category` it was observed firing under — and moves the scan to its terminal `COMPLETED` status. Detection deduplicates observations by signature, first observation winning, and then classifies each distinct tracker: if no `APPROVED` vendor of the property declares the signature, a `TrackerFinding` is created with `violation_type` `UNAUTHORIZED_TRACKER`, `severity` `HIGH`, and a null `vendor_id`; if the earliest-registered matching `APPROVED` vendor declares the signature but not the observed purpose, a `PURPOSE_MISMATCH` finding with `severity` `MEDIUM` is created against that vendor; a fully conforming observation produces nothing. The scan reports `findings_created_count` and `unauthorized_findings_count`.

Every finding begins `OPEN`, tied to its scan through `scan_id`, and is adjudicated along two branches: remediation by a `VendorManager` (`OPEN → REMEDIATED`, recording `remediated_by_user_id`), or violation confirmation by a `ComplianceAuditor` (`OPEN → CONFIRMED_VIOLATION`, recording `confirmed_by_user_id`), and either terminal-adjacent state can be closed by a `ComplianceAuditor` (`→ CLOSED`). Closing directly from `OPEN`, or any other unlisted hop, fails with `ERR_FINDING_INVALID_STATE`. Two governance rules guard confirmation. The adjudication operation is role-split by payload: a `VendorManager` may request remediation but a confirmation from them is refused with `ERR_INSUFFICIENT_PERMISSIONS`. And segregation of duties is enforced by identity — the auditor whose identifier is recorded as the scan's `created_by_user_id` may not confirm violations on their own scan; the attempt is rejected with `ERR_SEGREGATION_OF_DUTIES_VIOLATION`, and a second auditor must confirm instead.

Vendor risk is scored on two deliberate variants, recomputed whenever findings are created or change status. `risk_score_strict` is the binary posture: one hundred if any of the vendor's findings stands at `CONFIRMED_VIOLATION`, zero otherwise. `risk_score_weighted` is graduated: the sum of severity weights — fifty per `HIGH`, twenty-five per `MEDIUM` — over the vendor's findings in `OPEN` or `CONFIRMED_VIOLATION`, capped at one hundred; findings that are `REMEDIATED` or `CLOSED` contribute nothing to either score. The two variants legitimately disagree: a vendor with one confirmed `MEDIUM` violation reads one hundred strict against twenty-five weighted.

### 3.8. Regulatory Sweeps and the Property Freeze

When a regulator opens an inquiry, a `ComplianceAuditor` registers a **RegulatorySweep** with the `property_id`, a `regulator_ref` case reference, the `jurisdiction_code` under scrutiny, and a `deadline_days` budget; the system stamps `response_due_at` as exactly that many days after creation. The sweep lifecycle runs `OPEN → EVIDENCE_COLLECTION → RESPONDED → CLOSED`, with escalation available from either `OPEN` or `EVIDENCE_COLLECTION`. Beginning evidence collection moves the sweep to `EVIDENCE_COLLECTION`; responding — a `PrivacyAdmin` duty — moves it to `RESPONDED`, and closing settles it. Actions from any other status are rejected with `ERR_SWEEP_INVALID_STATE`.

The deadline has teeth. If the logical clock has passed `response_due_at` when a response is attempted, the sweep does not accept the response: it auto-transitions to `ESCALATED` and the respond call fails with `ERR_SWEEP_DEADLINE_PASSED`. The same escalation happens lazily on any read once the deadline has passed, per §2.4. A `ComplianceAuditor` may also escalate manually at any time while the sweep is unresolved.

Escalation is the system's deepest cascade. The sweep stamps `escalated_at` and computes its `penalty_exposure_cents` (below); the property's `posture` flips to `FROZEN` (incrementing its `version`); the freeze then pushes each `PUBLISHED` banner configuration of the property to `SUPPRESSED`; and each suppressed configuration in turn disables its `ENABLED` tag rules. Every link is caused by the previous one. The penalty is computed over all of the property's tracker findings standing in `CONFIRMED_VIOLATION` at the escalation moment: for each finding, the system takes the finding's age in whole days from its `created_at` to `escalated_at` (fractional days discarded), caps that age at thirty days, multiplies the severity base — 250000 cents for `HIGH`, 77777 cents for `MEDIUM` — by one plus five hundredths per day of age (capped), rounds the resulting per-finding amount half-up to whole cents, and only then sums the rounded amounts into `penalty_exposure_cents` (§2.9 pins this round-then-sum order).

Closing an `ESCALATED` sweep (or a `RESPONDED` one) moves it to `CLOSED`; if it was the property's last escalated sweep, the posture returns to `NORMAL`. Suppressed configurations and disabled tag rules are not automatically restored — the team re-publishes configurations (§3.2) and re-enables rules (§3.3) under the normal gates.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources return a `201 Created` status code (property, policy, banner configuration, vendor, tag rule, visitor, GPC signal event, consent record, do-not-sell request, tag audit scan, regulatory sweep). Operations that modify an existing resource — status transitions, publications, acknowledgements, clock setting — return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/v1/properties` | Create a property | PrivacyAdmin |
| GET | `/v1/properties` | List properties | Any |
| GET | `/v1/properties/{id}` | Get a property | Any |
| POST | `/v1/_clock/set_current_utc` | Set the logical clock | PrivacyAdmin |
| POST | `/v1/jurisdiction-policies` | Create a jurisdiction policy | PrivacyAdmin |
| GET | `/v1/jurisdiction-policies` | List jurisdiction policies | Any |
| GET | `/v1/jurisdiction-policies/{id}` | Get a jurisdiction policy | Any |
| PUT | `/v1/jurisdiction-policies/{id}` | Transition status or amend retention | PrivacyAdmin |
| POST | `/v1/banner-configs` | Create a banner configuration | PrivacyAdmin |
| GET | `/v1/banner-configs` | List banner configurations | Any |
| GET | `/v1/banner-configs/{id}` | Get a banner configuration | Any |
| POST | `/v1/banner-configs/{id}/publish` | Publish a configuration (OCC) | PrivacyAdmin |
| POST | `/v1/banner-configs/{id}/archive` | Archive a draft configuration | PrivacyAdmin |
| POST | `/v1/vendors` | Register a vendor | VendorManager |
| GET | `/v1/vendors` | List vendors | Any |
| GET | `/v1/vendors/{id}` | Get a vendor | Any |
| POST | `/v1/vendors/{id}/approve` | Approve a vendor | PrivacyAdmin |
| POST | `/v1/vendors/{id}/suspend` | Suspend a vendor | PrivacyAdmin |
| POST | `/v1/tag-rules` | Create a tag rule | VendorManager |
| GET | `/v1/tag-rules` | List tag rules | Any |
| GET | `/v1/tag-rules/{id}` | Get a tag rule | Any |
| PUT | `/v1/tag-rules/{id}` | Transition a tag rule | VendorManager |
| POST | `/v1/visitors` | Register a visitor | Anonymous |
| GET | `/v1/visitors` | List visitors | Any |
| GET | `/v1/visitors/{id}` | Get a visitor | Any |
| POST | `/v1/visitors/{id}/age-attestation` | Attest visitor birthdate | Visitor |
| POST | `/v1/visitors/{id}/gpc-signals` | Record a GPC signal | Visitor |
| GET | `/v1/visitors/{id}/gpc-signals` | List a visitor's GPC events | Any |
| GET | `/v1/visitors/{id}/consent-preview` | Preview the effective consent decision | Any |
| POST | `/v1/visitors/{id}/consent-records` | Grant consent for a purpose | Visitor |
| GET | `/v1/visitors/{id}/consent-records` | List a visitor's consent records | Any |
| GET | `/v1/consent-records` | List consent records across a property | Any |
| GET | `/v1/consent-records/{id}` | Get a consent record | Any |
| POST | `/v1/consent-records/{id}/withdraw` | Withdraw consent | Visitor |
| POST | `/v1/consent-records/{id}/regrant` | Re-grant a withdrawn record | Visitor |
| POST | `/v1/visitors/{id}/do-not-sell-requests` | Submit a do-not-sell request | Visitor |
| GET | `/v1/visitors/{id}/do-not-sell-requests` | List a visitor's requests | Any |
| GET | `/v1/do-not-sell-requests` | List requests across a property | Any |
| GET | `/v1/do-not-sell-requests/{id}` | Get a do-not-sell request | Any |
| PUT | `/v1/do-not-sell-requests/{id}` | Verify or reject a request | PrivacyAdmin |
| POST | `/v1/do-not-sell-requests/{id}/propagate` | Dispatch vendor propagations | PrivacyAdmin |
| GET | `/v1/do-not-sell-requests/{id}/propagations` | List a request's propagations | Any |
| GET | `/v1/vendor-propagations` | List propagations by vendor | Any |
| GET | `/v1/vendor-propagations/{id}` | Get a propagation | Any |
| PUT | `/v1/vendor-propagations/{id}` | Confirm, fail, or retry a propagation | VendorManager |
| POST | `/v1/tag-audit-scans` | Schedule a tag audit scan | ComplianceAuditor |
| GET | `/v1/tag-audit-scans` | List tag audit scans | Any |
| GET | `/v1/tag-audit-scans/{id}` | Get a scan | Any |
| POST | `/v1/tag-audit-scans/{id}/run` | Run a scan over observed trackers | ComplianceAuditor |
| GET | `/v1/tag-audit-scans/{id}/findings` | List a scan's findings | Any |
| GET | `/v1/vendors/{id}/tracker-findings` | List a vendor's findings | Any |
| PUT | `/v1/tracker-findings/{id}` | Remediate, confirm, or close a finding | VendorManager, ComplianceAuditor |
| POST | `/v1/regulatory-sweeps` | Open a regulatory sweep | ComplianceAuditor |
| GET | `/v1/regulatory-sweeps` | List regulatory sweeps | Any |
| GET | `/v1/regulatory-sweeps/{id}` | Get a sweep | Any |
| POST | `/v1/regulatory-sweeps/{id}/begin-evidence-collection` | Begin evidence collection | ComplianceAuditor |
| POST | `/v1/regulatory-sweeps/{id}/respond` | Respond to a sweep | PrivacyAdmin |
| POST | `/v1/regulatory-sweeps/{id}/escalate` | Escalate a sweep | ComplianceAuditor |
| POST | `/v1/regulatory-sweeps/{id}/close` | Close a sweep | PrivacyAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_INSUFFICIENT_PERMISSIONS` | 403 Forbidden |
| `ERR_FORBIDDEN_OWNERSHIP` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_PROPERTY_NOT_FOUND` | 404 Not Found |
| `ERR_POLICY_NOT_FOUND` | 404 Not Found |
| `ERR_BANNER_CONFIG_NOT_FOUND` | 404 Not Found |
| `ERR_VENDOR_NOT_FOUND` | 404 Not Found |
| `ERR_TAG_RULE_NOT_FOUND` | 404 Not Found |
| `ERR_VISITOR_NOT_FOUND` | 404 Not Found |
| `ERR_CONSENT_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_DNS_REQUEST_NOT_FOUND` | 404 Not Found |
| `ERR_PROPAGATION_NOT_FOUND` | 404 Not Found |
| `ERR_SCAN_NOT_FOUND` | 404 Not Found |
| `ERR_FINDING_NOT_FOUND` | 404 Not Found |
| `ERR_SWEEP_NOT_FOUND` | 404 Not Found |
| `ERR_STALE_PROPERTY_VERSION` | 412 Precondition Failed |
| `ERR_PROPERTY_FROZEN` | 409 Conflict |
| `ERR_POLICY_INVALID_TRANSITION` | 409 Conflict |
| `ERR_BANNER_CONFIG_NOT_PUBLISHABLE` | 409 Conflict |
| `ERR_VENDOR_INVALID_TRANSITION` | 409 Conflict |
| `ERR_TAG_RULE_INVALID_TRANSITION` | 409 Conflict |
| `ERR_CONSENT_INVALID_TRANSITION` | 409 Conflict |
| `ERR_DNS_INVALID_STATE` | 409 Conflict |
| `ERR_PROPAGATION_INVALID_STATE` | 409 Conflict |
| `ERR_SCAN_NOT_RUNNABLE` | 409 Conflict |
| `ERR_FINDING_INVALID_STATE` | 409 Conflict |
| `ERR_SWEEP_INVALID_STATE` | 409 Conflict |
| `ERR_SWEEP_DEADLINE_PASSED` | 409 Conflict |
| `ERR_AGE_UNVERIFIED` | 409 Conflict |
| `ERR_CHILD_CONSENT_FORBIDDEN` | 403 Forbidden |
| `ERR_NO_ACTIVE_POLICY` | 409 Conflict |
| `ERR_VENDOR_NOT_APPROVED` | 409 Conflict |
| `ERR_CROSS_PROPERTY_REFERENCE` | 409 Conflict |
| `ERR_POLICY_OUTSIDE_COVERAGE_WINDOW` | 409 Conflict |
| `ERR_SCAN_WINDOW_CONFLICT` | 409 Conflict |
| `ERR_POLICY_WINDOW_OVERLAP` | 409 Conflict |
| `ERR_DUPLICATE_TAG_RULE` | 409 Conflict |
| `ERR_DUPLICATE_CONSENT_PURPOSE` | 409 Conflict |
| `ERR_DNS_NOT_APPLICABLE` | 409 Conflict |
| `ERR_SEGREGATION_OF_DUTIES_VIOLATION` | 403 Forbidden |
