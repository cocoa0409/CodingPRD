# Worklog — task_1611_fog (FOG Ordinance Compliance Program)

## Step 1: Create Task Directory — 2026-08-14T01:35:00.000Z

Task directory `tasks/task_1611_fog/` and `workspace/` pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per invocation instructions; no index scan performed, no other task directory touched.

## Step 2: Generate Scaffold — 2026-08-14T02:27:00.000Z

Scaffold generation complete for the FOG (Fats/Oils/Grease) Ordinance Compliance Program. All artifacts written, lint clean, and quality checks pass.

**Output files**
- `/home/ubuntu/github/CodingPRD/tasks/task_1611_fog/SCAFFOLD.yaml` — §1.0–§1.7 only (response envelope verbatim; no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1611_fog/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design` (§1.8)
- `/home/ubuntu/github/CodingPRD/tasks/task_1611_fog/SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design` (§1.9)

**Counts**
- Entities: 11 (Establishment, GreaseInterceptor, Inspection, Violation, PumpManifest, Hauler, DisposalRecord, BlockageEvent, VarianceRequest, EducationCampaign, OutreachEvent)
- State machines: 8 (incl. cyclic VarianceRequest info-loop, cyclic Hauler suspend/reinstate, posture-driven Establishment) + 2 OCC concurrency rules
- Endpoints: 50 (incl. `POST /sweeps/run` and `POST /_clock/set_current_utc` with pinned default `2026-08-01T00:00:00Z`)
- Errors: 28
- Roles: 5 (ProgramAdmin/Inspector/ComplianceOfficer opaque; FseContact→Establishment and HaulerAdmin→Hauler entity-backed; segregation-of-duties model)
- Calculations: 9
- §1.8 instances: 18 (2 per rule × 9 rules)
- §1.9 instances: 42 active + 9 `excluded_because` stubs (all stub refs resolve to §1.8 instance names)

**Profile**: Compliance/audit primary archetype, flat topology, cyclic machine shape; layers = optimistic concurrency, cascading side effects, rate/threshold triggers, derived-field reconciliation. Expert-leaning density.

**Difficulty highlights** (all §1.8 asserts use literals computed from the formulas): dual-variant calcs on two domains (interceptor sizing provisional 495 vs measured 600; pumping delinquency forward-looking `pumping_overdue==false` vs chronological `missed_pump_windows==1` on identical data); combinatorial formulas in modes (a) and (b) (capped weighted risk score = 90 vs uncapped 170; per-share round-half-up + largest-weight remainder yielding 3300/3300/3401 on 10001 cents); two depth-3 transitive cascades from different triggers (manifest-reject → mismatch_count → hauler auto-suspend → orphan manifests auto-rejected; sweep escalation → CITATION → SUSPENDED posture → variances auto-denied); priority conflicts on distinct category pairs (safety>referential; state>temporal); half-open variance windows vs 14-day campaign zone buffers; compensating invariants on currency (budget record/void) and count (open violations create/dismiss).

**Verification**: `scaffold_lint.py` verdict — `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5` (359 calls scanned). One fix was needed during lint (added `inspection_id?` filter to `GET /violations` for FK reverse-reachability). Forbidden concurrency vocabulary: none. Instance names unique across both design files (69 total, no duplicates). No sibling tasks were consulted.

## Step 3: Copy Shared Files — 2026-08-14T02:27:30.000Z

Copied ./INSTRUCTION.md → tasks/task_1611_fog/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-14T02:55:00.000Z

All checks pass. The generation is complete and verified.

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1611_fog/workspace/PRD.md` — 299 lines.

**Section list**:
- §1 Introduction (2 paragraphs, business-context + segregation-of-duties angle)
- §2 Global Specifications — 2.1 RBAC, 2.2 API Response Structure (verbatim block), 2.3 Pagination, 2.4 The Logical Program Clock, 2.5 Common Resource Properties, 2.6 Optimistic Concurrency Control, 2.7 Derived Posture and Cascading Reconciliation, 2.8 Monetary Values/Rounding/Precision, 2.9 Request Validation Order
- §3 Business Logic — 3.1 Establishment Enrollment & Risk Classification, 3.2 Interceptor Sizing/Approval/Commissioning, 3.3 Inspections/Scoring/Violation Escalation, 3.4 Hauler Permitting/Manifests/Disposal Reconciliation, 3.5 Pumping Delinquency & Compliance Sweep, 3.6 Blockage Investigation & Cost Recovery, 3.7 Variance Requests, 3.8 Education Campaigns & Outreach Budgeting
- §4 Endpoint Definitions (4-column table), §5 Error Code Catalogue (2-column table)

**Coverage counts**:
- Entities: 11/11; entity fields 80/80 present in backticks (incl. nested `category`/`severity`/`weight_percent`/`share_cents`/`paid_at` and common fields)
- Endpoints: 50/50 rows in §4; request-body/output identifiers 47/47; query params 10/10
- Errors: 28/28 rows in §5; all 28 IDs also mentioned with trigger context in §2/§3
- State/enum values: 44/44 exact strings present
- Calculations: 9/9 rendered as precise prose (risk scoring, dual-variant interceptor sizing, inspection scoring, dual-variant delinquency, posture priority, half-up-per-share cost apportionment, 5% strict disposal tolerance, citation fines, campaign budget invariant)
- Transitions: 28/28 expressed with preconditions + error IDs + side effects; OCC rules 2/2 (`expected_establishment_version` on establishment PATCH and variance approve, `ERR_STALE_VERSION`/412); validation priority chain 13/13 in §2.9 as an explicit ordered list
- Contract 1: PASS (0 missing). Contract 3: PASS (156 §3 backtick tokens, no paths/methods). No pseudocode/operator leakage; all formulas pass the reconstruction test with exact thresholds and boundary inclusivity stated.

**Zero-Silence Rule notes** (scaffold items not renderable verbatim, resolved as follows):
1. `permit_number` uniqueness across haulers has no dedicated error ID in the catalog — the requirement is stated in §3.4 prose without an attached error (inventing one would violate no-invention).
2. Clock-set monotonicity: validation 11 says "non-decreasing" while the endpoint description and `ERR_CLOCK_REGRESSION` condition both say "strictly after" — I rendered strictly-after (the more specific, mutually consistent sources).
3. Validation 9's group HTTP status is 409, but the error catalog assigns `ERR_INSURANCE_EXPIRED` 422 — §5 renders per-error catalog statuses (422), and §3.4 states 422 for that error.
4. Disposal-create "manifest must be `SUBMITTED`" has no dedicated error ID — expressed in §3.4 as a from-state requirement, falling under the `ERR_INVALID_STATE` category per validation priority 6.
5. `api_prefix` is empty in the scaffold, so no mount-prefix statement appears.

## Step 5: Generate Unit Tests — 2026-08-14T03:20:00.000Z

Generation complete. Here is the summary.

**Task:** task_1611_fog — FOG Ordinance Compliance Program test suite.

### Tests emitted
- **Queue A (Difficulty):** 18/18 instances covered, **37 tests** (each instance has ≥2 tests)
- **Queue B (Corner):** 42/42 non-stub instances covered, **45 tests**
- **Total: 82 tests**, all collected cleanly by pytest

### Instances skipped
None. Every non-stub instance in both queues passed the PRD-first two-condition filter. The 9 `excluded_because:` stubs in queue B were not translated (per spec); all 9 stub `difficulty_instance:` cross-references were verified to resolve to real §1.8 instances.

### Files written
`test_helpers/` (Stage 1):
- `test_helpers/types.py` — 10 entity TypedDicts (Inspection/DisposalRecord correctly append-only: no `updated_at`/`version`), 13 status/field enums, 5-role `UserRole`
- `test_helpers/api_client.py` — 40 endpoint methods covering every PRD endpoint including `/_clock/set_current_utc` and `/sweeps/run`
- `test_helpers/api_errors.py` — all 28 error IDs with HTTP status map registered via `set_error_http_status_map`
- `test_helpers/assertions.py` — per-entity assertions plus `assert_campaign_budget_invariant`
- `test_helpers/factories.py` — input-only payload factories
- `test_helpers/constants.py` — risk caps/thresholds, sizing constants, severity deductions/fines/cure days, 0.05 tolerance, 14-day buffer, default clock
- `test_helpers/test_users.py` — opaque shared constants for ProgramAdmin/Inspector/ComplianceOfficer + mandatory per-instance builders `make_fse_contact_headers`/`make_hauler_admin_headers` for the entity-backed roles
- `test_helpers/fixtures.py` — tiered composites: `setup_pumping_chain`, `setup_submitted_manifest`, `setup_verified_manifest`, `create_active_interceptor`, `create_failing_inspection`, `create_and_approve_variance`, `create_and_assess_blockage`, `set_clock`, etc., all threading entity-backed identity correctly
- `test_helpers/__init__.py` — barrel export

`test_suite/` (Stage 2):
- `test_suite/conftest.py`
- `test_01_registry_and_rbac.py` (13 tests) — creation defaults, 400/404, computed-field override, pagination, append-only shape, 401/403/ownership/SoD, error envelope, both OCC rules, derived-field recompute
- `test_02_risk_and_sizing.py` (7 tests) — capped risk formula, inclusive 70/40 boundaries, frequency table, provisional-vs-measured sizing, 50-gal floor + undersize boundary, invalid commission, immediate consistency
- `test_03_inspections_and_violations.py` (8 tests) — score constants/floor, 70-passes/69-fails boundary, cure deadline/fine zero, escalation temporal boundary, terminal lockdown, count-restoration invariants
- `test_04_haulers_manifests_disposal.py` (10 tests) — hauler cycle + mismatch reset, revoke terminality, insurance expiry, initial states, interceptor-active gate, duplicate manifest/disposal, 5% tolerance boundary, mismatch verify
- `test_05_cascades_and_sweep.py` (8 tests) — hauler-permit verify gate, suspended-establishment variance gate, depth-3 reject cascade, manual-suspend cascade, sweep escalation → SUSPENDED → variance denial (plus decided_at/approved_by null), sweep delinquency, forward-vs-chronological lenses, strict-> overdue boundary
- `test_06_variance_requests.py` (7 tests) — info cycle ×2 + justification replacement, per-scope uniqueness, half-open adjacency vs overlap, per-scope overlap, safety-beats-referential and state-beats-temporal priority pairs
- `test_07_blockage_cost_recovery.py` (5 tests) — 33/33/34 rounding + largest-weight remainder, 50/50 negative-remainder tie-break to earliest-created, empty/≠100-weight guards, unpaid close, happy path
- `test_08_campaigns_and_clock.py` (8 tests) — 14-day buffer boundary, overlap vs other-zone, exact-fit budget + 1-cent-over, void compensating credit, voided-excluded sum, event window, clock regression + equal-value rejection

### Audits
- **Design-tag audit:** all 82 tests carry exactly one `Design:` line; every tag resolves to a real instance; zero orphans; zero untagged.
- **PRD-citation sweep:** all 146 quoted PRD passages survive literal (whitespace-normalized) grep of `workspace/PRD.md`; three initial failures were fixed (one endpoint-titular citation replaced with the rule-bearing sentence, one typo, one non-verbatim fragment).
- **No forbidden markers:** no `skip`/`skipif`/`xfail`, no "scaffold" references in generated code.

## Step 6: Generate Implementation — 2026-08-14T03:40:00.000Z

Implementation complete and verified. Summary:

**Files written (all under `workspace/implementation/`)**
- `start.sh` — executable launcher; guarded dependency install (`if ! python3 -c "import flask"`), then `exec python3 app.py` in the foreground
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask entry point; binds `0.0.0.0:$PORT` (default 10000); registers blueprints; envelope-shaped handlers for ApiError/400/404/405/500
- `db.py` — in-memory `STORE` dicts per entity + logical clock (initial value exactly `2026-08-01T00:00:00Z`, never wall clock)
- `errors.py` — `ApiError` + all 28 error-ID constants from PRD §5
- `response.py` — envelope helpers (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields in `meta` for lists)
- `middleware.py` — `X-User-ID`/`X-User-Role` auth, role checks, ownership helpers, `limit`/`offset` pagination (default 10, min 1, max 100), created_at-ascending sort
- `validation.py` — priority-2 body-shape validators (typed ints rejecting bools, enums, conditional `requested_frequency_days`, `end > start` window rules, ISO-8601 parsing truncated to second precision)
- `services/calculations.py` — all 9 calculation rules
- `services/posture.py` — posture recompute, SUSPENDED variance-denial cascade, hauler-suspension manifest cascade
- `services/serializers.py` — per-entity serializers with live computed fields (`open_violation_count`, `pumping_frequency_days`, `pumping_overdue`, `missed_pump_windows`, `remaining_budget_cents`)
- `routes/` — 11 blueprints: establishments, interceptors, inspections, violations, manifests, haulers, disposals, blockages, variances, campaigns, ops

**Endpoints: 50 total** (3 establishments, 5 interceptors, 3 inspections, 5 violations, 5 pump-manifests, 6 haulers, 3 disposal-records, 5 blockage-events, 7 variance-requests, 3 campaigns, 3 outreach-events, sweep, clock)

**State machines implemented (8):** Establishment posture (derived, cyclic, SUSPENDED>DELINQUENT>WATCH>COMPLIANT), GreaseInterceptor (PROPOSED→APPROVED→ACTIVE), Violation (NOTICED→CITATION/RESOLVED/DISMISSED with SoD on dismiss), PumpManifest (SUBMITTED→VERIFIED/REJECTED with mismatch→auto-suspend→cascade chain), Hauler (APPLIED→PERMITTED⇄SUSPENDED→REVOKED, mismatch_count reset on reinstate), BlockageEvent (REPORTED→ASSESSED→CLOSED, SoD on close, unpaid-share gate), VarianceRequest (UNDER_REVIEW⇄INFO_REQUESTED→APPROVED/DENIED, OCC + suspension cascade), OutreachEvent (RECORDED→VOIDED compensating credit).

**Calculation functions (9):** `risk_classification` (Decimal, 1dp, inclusive 70/40 thresholds), `interceptor_required_capacity` (provisional/measured variants, ceil per variant, MEASURED only when strictly larger), `inspection_score` (severity deductions, 70 pass boundary, highest-severity violation), `pumping_delinquency` (both forward-looking `pumping_overdue` and chronological `missed_pump_windows` half-open windows), `compliance_posture`, `cost_share_apportionment` (round-half-up per share first, remainder to largest weight with earliest-created_at tie-break), `disposal_tolerance` (float ratio, strict `> 0.05`), `citation_fine`, `campaign_budget`.

**Verification:** two live smoke suites (136 checks total, 0 failures) covering auth/role/ownership ordering, OCC 412s, escalation deadline boundary, tolerance boundary (exactly 0.05 passes), auto-suspend cascades, variance window overlap with half-open adjacency, campaign 14-day buffer, budget debit/credit invariant, sweep auto-escalation, pagination meta, and validation-priority ordering. Confirmed `start.sh` cold-boots with an empty store, default clock, and binds `0.0.0.0:$PORT` in the foreground via `exec`.

## Step 7: Run Tests and Iterate — 2026-08-14T03:58:00.000Z

All 8 rounds pass 82/82. Clean sweep achieved.

**Summary**

- **Iterations run:** 2 (initial sweep: 7 deterministic failures, identical across all 8 rounds; post-fix sweep: 82/82 in all 8 rounds).

- **Tests deleted:** none — every failing test traced to a verbatim PRD rule; all failures were test-side setup bugs (STEP 2), not PRD-silence or derivability collapses.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`** (7 tests, 4 files; every fix makes the setup more PRD-faithful, no assertion weakened):
  - `test_01_registry_and_rbac.py::test_filtered_manifests_list_pagination` — setup created two manifests on the same interceptor with the same `pump_date` (`h1@2026-08-01` and `h2@2026-08-01`), violating PRD's verbatim rule "at most one manifest may exist for a given interceptor and `pump_date`". Changed H2's `pump_date` to `2026-08-03`.
  - `test_04_haulers_manifests_disposal.py::test_hauler_suspend_then_reinstate_allows_filing_again` — setup suspended a PERMITTED hauler and then filed a disposal against its pre-existing manifest; PRD's suspension cascade ("every pump manifest still in `SUBMITTED` status that names the hauler is rejected in the same motion") had already rejected that manifest, so §2.9 priority 6 (`ERR_INVALID_STATE`) correctly pre-empts priority 9 (`ERR_HAULER_NOT_PERMITTED`). Fixed by submitting a fresh manifest *during* the suspension (submission gates only interceptor-ACTIVE per PRD §2.9 item 9) and asserting the hauler gate against it.
  - `test_05_cascades_and_sweep.py::test_manifest_verify_requires_permitted_hauler` — same cascade bug, plus its second half verified a terminally-REJECTED manifest. Fixed to use a registered-but-never-permitted (APPLIED) hauler, then permit + file disposal + verify succeeds.
  - `test_05_cascades_and_sweep.py::test_sweep_marks_delinquent_establishment`, `test_pumping_delinquency_forward_vs_chronological`, `test_overdue_at_strictly_after_boundary` — all three called `set_clock("2026-01-01T00:00:00Z")`, a backward jump the PRD forbids ("The new value must be strictly after the current value" from the pinned `2026-08-01T00:00:00Z` start). Scenarios shifted forward to the default-clock baseline (deadline `2026-08-01`+90d=`2026-10-30`; 365d delinquency at `2027-08-02`; dual-lens windows W1 `[2026-08-01, 2026-10-30)` empty, W2 `[2026-10-30, 2027-01-28)` satisfied by a `2026-12-25` pump, evaluated at `2027-02-14` — same missed=1/overdue=false divergence as the original design).
  - `test_06_variance_requests.py::test_verify_manifest_safety_beats_referential` — same suspension-cascade bug; replaced suspend with an APPLIED hauler so the manifest stays SUBMITTED and the priority-9-vs-10 ordering (hauler gate beats interceptor-mismatch) is exercised as PRD intends. Added `create_hauler` to imports.

- **Fixes applied to `implementation/`:** none — the implementation was PRD-faithful in every failure (cascade semantics, §2.9 validation ordering, clock monotonicity, and manifest uniqueness all matched PRD verbatim).

## Step 8: Finalize PRD — 2026-08-14T04:05:00.000Z

All verification is complete. The conclusion is **zero edits** — `PRD_FINALIZED.md` exists as an exact byte-identical copy of `PRD.md` (verified via `diff -q`).

**Line counts / delta:** `PRD.md` 299 lines, `PRD_FINALIZED.md` 299 lines, 0.0% delta (exact copy).

**Changes:** none. Every one of the 7 step_7 fixes was a test-side fixture bug that violated a rule the PRD already states verbatim, and the implementation is PRD-faithful at each site. No PRD silence or mismatch was exposed, so the hard scope permits no edit.

### Per-item no-edit rationale (with mandatory pre-edit search log)

1. **test_01 manifest uniqueness** — (a) one manifest per interceptor + `pump_date`. (b) `implementation/routes/manifests.py:55-57` (uniqueness scan), PRD §3.4 line 161 (verbatim rule + `ERR_DUPLICATE_MANIFEST` 409), §2.9 item 12. (c) none needed.
2. **test_04 suspension cascade vs disposal gate order** — (a) cascade rejection of SUBMITTED manifests on suspension; `ERR_INVALID_STATE` over `ERR_HAULER_NOT_PERMITTED`. (b) `implementation/services/posture.py:33-44` (cascade shared by manual + auto-suspend via `routes/manifests.py:158-165`), `implementation/routes/disposals.py:31-34`, `implementation/routes/haulers.py:78-86`; PRD §2.7 line 97 + §3.4 line 159 cascade verbatim, §2.9 priorities 6 < 9 + worked example line 121. (c) none needed.
3. **test_05 verify requires PERMITTED hauler** — (a) verify only from SUBMITTED + hauler gate. (b) `implementation/routes/manifests.py:120-127`; PRD §3.4 line 165 fixed four-check sequence. (c) none needed.
4–6. **test_05 sweep/delinquency clock monotonicity** — (a) initial clock value + strict-advance rule. (b) `implementation/db.py:31-34` (`INITIAL_CLOCK = 2026-08-01T00:00:00Z`), `implementation/routes/ops.py:46-56` (`ERR_CLOCK_REGRESSION`); PRD §2.4 line 76 pins both verbatim. (c) none needed.
7. **test_06 priority 9 beats 10** — (a) hauler gate precedes interceptor-mismatch at verification. (b) `implementation/routes/manifests.py:122-127`; PRD §2.9 items 9–10 + worked example line 121. (c) none needed.

**Files:** `workspace/PRD_FINALIZED.md` (written, byte-identical to `workspace/PRD.md`).

## Step 9: Complete PRD — 2026-08-14T04:25:00.000Z

Done. `workspace/PRD_COMPLETED.md` written as a minimal patch over PRD_FINALIZED.md (copied, then edited in place; no new sections, all changes inline).

**Size delta**
- PRD_FINALIZED.md: 299 lines, 44,851 chars
- PRD_COMPLETED.md: 301 lines, 48,794 chars
- Delta: +2 lines, +3,943 chars

**Counts**
- Ambiguity-pins: 16
- Mismatch-revisions: 2

**Changes**
- §2.1 — revise — mismatch — carved blockage reads out of the FseContact "reads limited to its own establishment's resources" blanket, deferring to §3.6's contribution-membership rule (impl allows any FseContact to read a contribution-less REPORTED blockage) — `routes/blockages.py:58-59`
- §2.2 — insert — ambiguity — pinned `api_request_timestamp` as wall-clock, not the logical program clock — `implementation/response.py:13-16`
- §2.2 — insert — ambiguity — pinned transport-level errors: unknown path → `ERR_NOT_FOUND` 404; unsupported method → 405 with `error_id` `ERR_NOT_FOUND`; malformed/non-object JSON body → `ERR_INVALID_REQUEST` 400; empty body treated as `{}`; unexpected failure → 500 `ERR_INTERNAL` in same envelope — `implementation/app.py:45-62`, `implementation/validation.py:15-25`
- §2.3 — revise — ambiguity — pinned pagination semantics: non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST` 400; sort ties broken by insertion order; out-of-set enum filters → 400; unknown id filters and overrun offsets yield empty pages, not errors; `has_more` ≡ offset + returned < total_count; query-parameter validation runs after role authorization — `implementation/middleware.py:45-86`
- §2.4 — insert — ambiguity — pinned datetime parsing (ISO 8601, timezone-less read as UTC, normalized to UTC at second precision) and that client-supplied datetimes are stored as supplied, clock-compared only where a rule says so — `implementation/validation.py:28-43`
- §2.5 — insert — ambiguity — pinned that all server-assigned resource timestamps (`created_at`, `updated_at`, `escalated_at`, `resolved_at`, `dismissed_at`, `decided_at`, `paid_at`) read the logical program clock — e.g. `implementation/routes/establishments.py:46-47`, `implementation/routes/violations.py:73-74`
- §2.5 — insert — ambiguity — pinned initial `version` = 1 at creation — `implementation/routes/establishments.py:48` (same pattern in every create handler)
- §2.8 — insert — ambiguity — pinned pumped/disposed volumes and measured flow as arbitrary positive numbers, not necessarily whole — `implementation/validation.py:76-87`, `implementation/routes/manifests.py:47`, `implementation/routes/disposals.py:24`, `implementation/routes/interceptors.py:34`
- §2.9 item 2 — revise — ambiguity — added numeric bounds (non-negativity / greater-than-zero minimums) to the `ERR_INVALID_REQUEST` shape checks, plus explicit JSON `null` ≡ omitted for optional fields and unnamed fields are ignored — `implementation/validation.py:52-117`
- §2.9 item 4 — revise — mismatch — pinned the real ownership/existence order: ownership decidable from request-supplied own-id (path or body) is evaluated directly before lookups; ownership read from a stored resource's foreign key requires loading the resource first, so a missing target reports `ERR_NOT_FOUND` before ownership — `implementation/routes/establishments.py:59-60`, `implementation/routes/haulers.py:56-57` vs `implementation/routes/interceptors.py:81-83`, `implementation/routes/violations.py:55-57`, `implementation/routes/manifests.py:108-111`, `implementation/routes/variances.py:140-141`
- §3.1 — revise — ambiguity — pinned that every accepted profile PATCH recomputes risk from the resulting profile and advances `version` by exactly one with `updated_at` refreshed, even when no stored value changes — `implementation/routes/establishments.py:93-97`, `implementation/services/posture.py:17-28`
- §3.4 — insert — ambiguity — pinned duplicate `permit_number` rejection as `ERR_INVALID_REQUEST` (400) — `implementation/routes/haulers.py:32-34`
- §3.5 — revise — ambiguity — pinned sweep list semantics: `escalated_violation_ids` in ascending violation creation order; `delinquent_establishment_ids` = every establishment whose post-sweep status is `DELINQUENT` (changed or not), in ascending establishment creation order — `implementation/routes/ops.py:22-39`
- §3.6 — insert — ambiguity — pinned the FseContact blockage-read rule: allowed only while the event carries no contributions or when its establishment is named among them — `implementation/routes/blockages.py:58-59`
- §3.6 — insert — ambiguity — pinned `weight_percent` as a non-negative integer and that the same establishment may appear in multiple contribution entries, each apportioned and paid independently — `implementation/routes/blockages.py:63-80`
- §3.6 — insert — ambiguity — pinned the remainder tie-break sub-rule: a further tie between entries naming the same establishment favors the earlier array entry — `implementation/services/calculations.py:154-166`
- §3.6 — insert — ambiguity — pinned payment routing: pays the first contribution entry naming the establishment; an establishment named in no entry → `ERR_NOT_FOUND` (404) — `implementation/routes/blockages.py:131-135`
- §3.8 — insert — ambiguity — pinned the 14-day zone buffer as exclusive and bidirectional: a gap of exactly 14 days is permitted, only a strictly smaller gap conflicts — `implementation/routes/campaigns.py:42-48`

Everything else in the implementation (all 40 endpoints' role sets, state machines, formulas, thresholds, fine/cure tables, tolerance boundary, cascade contents, OCC orderings, envelope shapes) was already uniquely pinned by PRD_FINALIZED.md and verified against the code with no change needed.
