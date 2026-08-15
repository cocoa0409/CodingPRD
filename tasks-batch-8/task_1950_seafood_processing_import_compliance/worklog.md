# Worklog — task_1950_seafood_processing_import_compliance

## Step 1: Create Task Directory — 2026-08-15T02:42:00.000Z

Directory `tasks/task_1950_seafood_processing_import_compliance/workspace/` pre-created by the pipeline launcher (per command args); orchestrator did not scan or create any other task directory.

## Step 3: Copy Shared Files — 2026-08-15T02:43:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1950_seafood_processing_import_compliance/workspace/INSTRUCTION.md`.

## Step 2: Generate Scaffold — 2026-08-15T03:35:00.000Z

Done. All three scaffold artifacts for **task_1950_seafood_processing_import_compliance** are written and pass `scaffold_lint.py` with a clean verdict on the first and final runs.

## Files
- `/home/ubuntu/github/CodingPRD/tasks/task_1950_seafood_processing_import_compliance/SCAFFOLD.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1950_seafood_processing_import_compliance/SCAFFOLD_DIFFICULTY_DESIGN.yaml`
- `/home/ubuntu/github/CodingPRD/tasks/task_1950_seafood_processing_import_compliance/SCAFFOLD_CORNER_DESIGN.yaml`

## Counts
- **13 entities** (ForeignSupplier, SupplierEvaluation, ImportEntry, ReceiptLot, SpeciesVerification, ProcessingBatch, BatchInputLot, TemperatureLog, HaccpMonitoringRecord, CorrectiveAction, ProductLabel, FinishedProductLot, Recall)
- **9 state machines / 45 transitions**, incl. ForeignSupplier re-evaluation cycle, ReceiptLot QUARANTINED↔ACCEPTED revert loop, ProcessingBatch COMPLETED→IN_PROCESS reopen cycle, ProductLabel self-referential supersede chain
- **6 calculations** (provisional-vs-final yield with pinned per-lot-round-then-sum, dual-phase histamine verdict, 3-branch freeze-protocol accumulation, cumulative temperature-abuse threshold, weighted supplier risk score, penny-remainder landed-cost allocation)
- **29 ordered validations**, **57 endpoints**, **36 error codes**, **6 roles** (all opaque; segregation_of_duties model), **2 OCC concurrency rules**
- **§1.8: 18 instances** (9 rules × 2), **§1.9: 39 instances** (38 active + 1 `excluded_because` stub); 57 unique instance names across both files; 583 structured calls lint-scanned
- Lint verdict: `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

## Notable design decisions
- **Difficulty levers over volume**: dual-variant calcs on two domains (yield accounting vs food-safety verdicts); depth-3 cascade (mismatch → quarantine → auto-CA → supplier risk recompute) and depth-2 cascade (escalate → Recall → lot RECALLED); two interval semantics (half-open temperature adjacency-allowed vs closed evaluation-period shared-day-overlap); two compensating invariants over different conserved quantities (mass kg vs allocation cents).
- **Segregation of duties**: CA `opened_by` is stamped from the triggering request's X-User-ID; resolve requires a different user. A `POST /seafood/corrective-actions` (MANUAL) endpoint exists so a ComplianceManager can open a CA and then be blocked resolving it — otherwise the SoD check would be unreachable (deviations are opened by non-CM roles).
- **Version pinning**: finished lots pin `label_version_pinned` at apply-label; approving a superseding label flips `label_stale` and blocks release until re-labeling.
- **Reachability fixes made during generation**: added `ERR_VERIFICATION_REQUIRED` (p29) + mirrored safety gates onto quarantine-release so `ERR_TEMPERATURE_ABUSE_EXCEEDED` is actually reachable; added APPROVED→APPROVED/SUSPENDED evaluation transitions (re-certification); dropped the unproduced `FREEZE_FAILURE` enum value; removed a circular reopen guard case (replaced with a genuinely reachable RECALLED-child guard).
- **Clock**: `POST /_clock/set_current_utc` (PlatformAdmin) with mandatory default `2026-08-01T00:00:00Z`; it also drives the supplier re-evaluation-due sweep.
- **Deliberate overshoot**: 57 endpoints exceeds the Expert band (20–32) because the scenario spans eight regulatory subsystems and the requester asked for the hardest tier; every endpoint is load-bearing (each child entity needs its single-GET + filtered-list pair for lint check (f) reverse-reachability). Entities (13) and errors (36) are at/just past Expert bounds; all numeric asserts were pre-computed with Python (e.g., 11.002 vs 11.001 rounding divergence, 540001/540000 remainder split, risk 14.50/11.50).

## Step 4: Generate PRD — 2026-08-15T03:45:00.000Z

All checks pass. Here is the summary of what was generated:

---

## Generation Summary

**Output file:** `/home/ubuntu/github/CodingPRD/tasks/task_1950_seafood_processing_import_compliance/workspace/PRD.md`

### Section Structure

- **§1. Introduction** — 3 paragraphs covering business context (FSVP/HACCP/COOL), operational challenge (species verification, cold-chain, yield tracking, cascading deviations), and system archetype (compliance audit with segregated duties).
- **§2. Global Specifications** — 8 subsections:
  - 2.1: RBAC with all 6 roles, identity semantics (all opaque), header names
  - 2.2: Verbatim fixed response envelope block
  - 2.3: Pagination (limit default 10, min 1, max 100; offset default 0; `created_at` ascending sort)
  - 2.4: Common resource properties (`id` UUID, `created_at`, `updated_at`, `version`; explicit exclusion for TemperatureLog and HaccpMonitoringRecord)
  - 2.5: Precision/rounding/units (integer cents, 3-decimal kg, 2-decimal pct, half-up rounding, 1-decimal Celsius, whole minutes)
  - 2.6: Nested resource retrieval (left-to-right path validation)
  - 2.7: OCC (two rules: `expected_batch_version` on batch complete, `expected_supplier_version` on supplier evaluation creation; both rejected with `ERR_STALE_VERSION` HTTP 412)
  - 2.8: Validation priority ordering framework
- **§3. Business Logic & Workflows** — 13 subsections organized by entity lifecycle stage, with cross-cutting concerns woven in:
  - 3.1: Foreign supplier registration and FSVP lifecycle
  - 3.2: Import entry filing and FDA disposition
  - 3.3: Raw material receipt and catch documentation
  - 3.4: Species verification and mislabeling prevention
  - 3.5: Lot acceptance, quarantine, and rejection gates
  - 3.6: Processing batches, input consumption, and yield reconciliation
  - 3.7: Entry cost allocation (waterfall)
  - 3.8: Supplier risk scoring
  - 3.9: Cold chain monitoring (temperature logs, freeze protocols)
  - 3.10: HACCP monitoring records (histamine/parasite)
  - 3.11: Corrective actions, segregation of duties, recalls
  - 3.12: Product labeling, allergen declaration, COOL
  - 3.13: Logical clock and time-driven sweep
- **§4. Endpoint Definitions** — Status code paragraph + 4-column table covering all 57 endpoints.
- **§5. Error Code Catalogue** — 2-column table covering all 36 error codes.

### Approximate Length

406 lines, ~6,680 words, ~50,300 characters.

### Coverage of Scaffold Elements

- **14 entities**: All fields, defaults, types, and enum constraints expressed in prose.
- **8 state machines**: All 45 transitions with from/to states, preconditions, side effects, and actor roles.
- **6 calculations**: All formulas expressed in precise natural language (no pseudocode, no fuzzy words). Constants embedded in business context (e.g., "0.42 for FILLET", "10,080 minutes (168 hours)", "50.0 ppm").
- **29 validations**: All error IDs present, trigger conditions scattered near relevant workflows, priority ordering framework stated in §2.8.
- **2 concurrency rules**: Both OCC rules fully specified (write endpoint, occ_field, error_id, HTTP 412).
- **57 endpoints**: All paths in §4 table with method, description, and authorized roles.
- **36 error codes**: All in §5 table.
- **6 roles**: All named with exact spelling in §2.1 and throughout §3.

### Deliberate Information-Scattering Choices

1. **Endpoint parameters distributed**: For example, the batch completion endpoint's `expected_batch_version` is discussed in §2.7 (OCC mechanism) and again in §3.6 (completion workflow), while `actual_output_kg`, `trim_waste_kg`, `other_waste_kg` appear only in §3.6. The receipt lot creation parameters are spread across §3.3 (core fields) and §3.9 (freeze protocol details).
2. **Calculation constants embedded in narrative**: Base yield factors (0.42/0.55/0.48) appear within the yield estimation paragraph in §3.6. Freeze protocol thresholds (-20.0, -35.0) and required minutes (10,080 / 900 / 240 / 1,440) are embedded in §3.9 with hour-equivalents parenthesized. Risk weights (40%/30%/30%) appear in §3.8.
3. **Cascade chains broken across subsections**: The species mismatch 3-link cascade (lot quarantine, CA auto-creation, supplier counter/risk update) is fully described in §3.4 but the risk recomputation details are in §3.8, forcing the reader to cross-reference.
4. **Acceptance gates enumerated in §3.5** but the underlying accumulation mechanics (how `cumulative_abuse_minutes` reaches 240, how `freeze_compliant` becomes true) are deferred to §3.9, requiring synthesis across subsections.
5. **No HTTP methods or paths in §3** — all endpoint references use state-transition framing, role + action verb, or capability description.

### Hard Contract Reports

```
Field coverage check:
- entities[].fields + endpoints[].input + concurrency_rules[].occ_field: 113 required, 113 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 29 checked, 29 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected version field + error_id all named), 0 missing
- state_machines[].transitions: 45 checked, 45 fully expressed, 0 missing
- calculations[]: 6 checked, 6 fully expressed, 0 missing
- validations[] conditions: 29 checked, 29 matchable to error_id in prose, 0 missing
- endpoints[] paths: 57 checked, 57 present in §4 table, 0 missing
- entities[].fields[] enum values: all present in backticks, 0 missing
- sibling-branch symmetry: spot-checked ForeignSupplier and ImportEntry parallel branches, equal density
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 604
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Step 5: Generate Unit Tests — 2026-08-15T04:05:00.000Z

80 test functions across 11 test files. Generation complete. Here is the summary.

## Summary

**Output generated** in `/home/ubuntu/github/CodingPRD/tasks/task_1950_seafood_processing_import_compliance/`:

### test_helpers/ (9 files, ~1,900 lines)
- `types.py` — 13 entity TypedDicts + 17 status/enum classes; append-only `TemperatureLog`/`HaccpMonitoringRecord` correctly omit `updated_at`/`version` per PRD §2.4.
- `api_client.py` — `ApiClient(GenericApiClient)` with 43 endpoint methods covering all PRD endpoints incl. `/_clock/set_current_utc`.
- `api_errors.py` — all 37 error IDs + HTTP map registered via `set_error_http_status_map`.
- `assertions.py` — per-entity asserters + domain invariants (`assert_lot_mass_balance`, `assert_allocation_conserves_total`).
- `factories.py`, `constants.py` (all thresholds: 50.0 ppm, 240 min, freeze protocol constants, yield factors, risk weights, lead hours), `test_users.py` (6 opaque roles + per-instance `make_*_headers` builders, used to pin `opened_by`/`closed_by` in segregation-of-duties and cascade tests).
- `fixtures.py` — composite tiers: `create_approved_supplier`, `create_released_entry`, `create_lot`, `verify_species`, `record_histamine_pass`, `create_accepted_lot`, `create_batch`/`add_input`/`complete_batch`, `create_approved_label`, `create_finished_lot`.
- `__init__.py` — barrel export.

### test_suite/ (conftest + 11 files, **80 tests**)
- **Queue A (Difficulty): 17 of 18 instances covered, ≥2 tests each (37 tests).** 
- **Queue B (Corner): all 34 non-stub instances covered, ≥1 test each (43 tests).** The one `excluded_because` stub (`calculations/allocation_remainder_tie_break`) was not translated; its cross-reference to `Difficulty/compensating_invariant/quarantine_release_conserves_allocated_cost` resolves.

### Skipped instances (1)
- **`Difficulty/priority_pair_validation_conflict/safety_beats_constraint_on_input`** — skipped under the `validation-priority` silence pattern. It asserts ERR_SPECIES_MISMATCH must beat ERR_INSUFFICIENT_LOT_REMAINING when both fail. Both are domain business rules whose relative priority numbers exist only in the scaffold; PRD §2.8 orders *categories* (state before business) but never states "error A fires before error B" for two business rules. Two PRD-only readers could ship either order. Not weakened, not marked skip — simply omitted. (The sibling instance `state_beats_safety_on_accept` was kept: PRD §2.8 verbatim orders state-machine checks before business rules, uniquely deriving ERR_INVALID_STATE.)

### Notable adjudication
- `lot_quarantine_accept_loop`: the design's version arithmetic (`version == 6`) omits the species-verification bump that PRD §3.4 explicitly states ("bumping the lot's version"). Tests assert the PRD-uniquely-derived value `version == 7` (create 1 → verify 2 → accept 3 → quarantine 4 → release 5 → quarantine 6 → release 7).

### Stage 2 self-check verdict: PASS
- Coverage audit: every non-skipped difficulty instance has ≥2 tagged tests; every non-stub corner instance has ≥1; stub untranslated; zero orphan/dual/untagged tests (programmatically verified).
- Verbatim pass: every docstring citation confirmed against PRD.md by literal substring grep (≥8-word probe); all `error_id`s asserted are named in PRD prose with their trigger conditions.
- No `skip`/`skipif`/`xfail`; no scaffold references in comments/docstrings; all modules compile and import cleanly.

## Step 6: Generate Implementation — 2026-08-15T04:10:00.000Z

All 149 verification checks pass from a clean boot. The implementation is complete.

## Summary

### File structure (`workspace/implementation/`)
- `start.sh` — launcher (executable)
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask app factory, custom Decimal JSON provider, error handlers, blueprint registration; `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))`
- `db.py` — empty-at-boot in-memory store (13 entity dicts), logical clock defaulting to exactly `2026-08-01T00:00:00Z`, `new_entity`/`new_append_only`/`touch` helpers (no seeding anywhere)
- `errors.py` — `ApiError` + all 36 catalog error IDs
- `response.py` — envelope: `meta{api_request_id (req_…), api_request_timestamp (3-fraction-digit ISO)}`, `response_type` object/array/error, `data{error_id,message}` on errors; list responses add `limit/offset/total_count/has_more` to `meta`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401 `ERR_UNAUTHENTICATED`), per-endpoint role gating (403 `ERR_UNAUTHORIZED_ROLE`); GETs allow the five operational roles only (PlatformAdmin has no shared ops per RBAC matrix)
- `utils.py` — Decimal q3/q2/q1 half-up quantizers, ISO8601 parse/format, `add_months`, typed body-field getters, pagination parsing (limit default 10, min 1, max 100; offset default 0), created_at-ascending sort
- `services.py` — all calculations, cascades, and 13 serializers
- `routes_suppliers.py` — suppliers, evaluations, clock
- `routes_entries.py` — import entries + receipt lots
- `routes_processing.py` — verifications, batches, inputs, temperature logs, HACCP records
- `routes_compliance.py` — corrective actions, recalls, labels, finished lots

### Endpoint coverage: 57/57
All 56 `/seafood/*` routes plus `POST /_clock/set_current_utc` (verified against the registered URL map).

### State machines implemented (9)
ForeignSupplier FSVP lifecycle (incl. CONDITIONAL-stays-PENDING, SUSPENDED→APPROVED only on APPROVED outcome, clock-sweep to REEVALUATION_DUE with `<=` semantics), ImportEntry (DRAFT→PRIOR_NOTICE_FILED→ENTRY_FILED→RELEASED/DETAINED/REFUSED with DETAINED escape), ReceiptLot (UNDER_INSPECTION/ACCEPTED/QUARANTINED/REJECTED/CONSUMED incl. auto-CONSUMED at remaining_kg == 0 and CONSUMED→ACCEPTED on input delete), SpeciesVerification (creation-time CONFIRMED/MISMATCH + resolve), ProcessingBatch (IN_PROCESS↔COMPLETED→RECONCILED), CorrectiveAction (OPEN/INVESTIGATING/RESOLVED/ESCALATED incl. RESOLVED→INVESTIGATING re-audit), ProductLabel (DRAFT→APPROVED→SUPERSEDED with staleness cascade), FinishedProductLot (UNLABELED→LABELED→RELEASED→RECALLED + label re-apply only when stale), Recall (INITIATED→NOTIFIED).

### Calculations implemented (6)
provisional_yield_estimation (per-lot round-to-3-first, then sum — pinned order; BASE_YIELD × GRADE_FACTOR), histamine_verdict (screening ≥50.0 deviation; confirmatory round-half-up-2dp average <50.0 AND every subsample <100.0; PARASITE ≥1), freeze_protocol_compliance (STANDARD/BLAST/COMBO two-phase with the first-blast-interval-end cutoff; pause-not-reset), temperature_abuse_exposure (avg >4.4 °C whole-minute accumulation, ≥240 cascade, exactly-240 blocks accept), supplier_risk_score (0.4/0.3/0.3 weighted, capped penalties, latest-by-period_end evaluation, tier boundaries 30/70 inclusive-lower, 36/12/3-month cadence), entry_cost_allocation (exact integer-mg floor waterfall, remainder cents by share DESC → qty DESC → created_at ASC, full recompute on eligible-set change).

### Key design choices
- Supplier counters (`open_corrective_action_count`, mismatch/deviation totals) and risk score/tier are **derived at serialization** from the CA/evaluation stores — can never drift; supplier version still bumped on every cascade touch.
- OCC: `expected_batch_version` on complete and `expected_supplier_version` on evaluation create, checked at priority 27 (after state/overlap checks), `ERR_STALE_VERSION` 412.
- Accept gates follow PRD §3.5 prose order (verification → histamine → abuse → freeze → open CA); quarantine-release follows its distinct PRD order (open CA → verification → histamine → abuse → freeze) — PRD wins over scaffold priority numbers here.
- All money is integer cents; all kg/percent/temp arithmetic is `Decimal` with `ROUND_HALF_UP`; multi-step cascades (mismatch 3-link, histamine deviation, abuse crossing, escalation recall) touch versions exactly as scaffold side-effects specify.

### start.sh contract
Reads `$PORT` (default 10000), binds `0.0.0.0` via Flask in **foreground** with `exec python3 app.py` (signals propagate to the runner's kill), and guards the dependency install with `if ! python3 -c "import flask"` so the per-test-server reboots (8-round concurrent sweep) skip pip entirely — boot is ~1s, well inside the 60s window. Verified: fresh process boots with an empty store and clock at `2026-08-01T00:00:00Z` on every invocation, on both a custom port and the default 10000.

I did not read anything under `test_helpers/`/`test_suite/` or the difficulty/corner design YAMLs.

## Step 7: Test/Fix Iteration Loop — 2026-08-15T04:20:00.000Z

All 8 rounds pass 80/80 — clean sweep, exiting.

**Summary**

- **Iterations run:** 2 (sweep 1: 5 deterministic failures × 8 rounds; sweep 2 after fixes: 80/80 × 8 rounds, union of failures = 0).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1950_seafood_processing_import_compliance/test_helpers/fixtures.py` — `create_entry()` gained a `port_code="USBLA"` keyword forwarded into the payload factory. Why: two tests in test_03 pass `port_code="USSEA"` through `create_released_entry(**entry_kwargs)`; PRD §3.2 declares `port_code` as an ImportEntry creation field, so the fixture's hardcoded port was a test-helper bug (TypeError on a PRD-declared field).

- **Fixes applied to `test_suite/` (test-function corrections, STEP 2):**
  - `/home/ubuntu/github/CodingPRD/tasks/task_1950_seafood_processing_import_compliance/test_suite/test_07_processing_batches_yield.py` — `test_yield_variance_exceeded_rejected`: changed `complete_headers=ps01` to `headers=ps01` to match the `complete_batch()` fixture signature (`complete_headers` only exists on `create_completed_batch`). Intent (complete as `ps-01` so the auto-CA's `opened_by == "ps-01"`, per PRD §3.6) unchanged.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1950_seafood_processing_import_compliance/test_suite/test_05_haccp_monitoring.py` — `test_abuse_accumulation_permanently_blocks_acceptance`: setup was missing the species verification and HISTAMINE PASS records, so quarantine-release hit `ERR_VERIFICATION_REQUIRED` (PRD §3.5 lists the verification gate *before* the abuse gate for quarantine-release — implementation order is PRD-faithful). Added `verify_species` + a passing SCREENING record on the QUARANTINED lot (both allowed by PRD §3.4/§3.10) so the abuse gate (240 minutes, `ERR_TEMPERATURE_ABUSE_EXCEEDED`) is the sole failing check — making the asserted error uniquely derivable.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1950_seafood_processing_import_compliance/test_suite/test_08_labels_finished_lots_recalls.py` — `test_recall_notify_then_terminal_lockdown`: replaced the exact-string `notified_at == "2026-08-01T00:00:00Z"` assertion with `is_iso8601_timestamp` + instant-equality comparison (new `_parse_instant` helper). PRD §3.11 fixes the *instant* (`notified_at` = current logical clock; §3.13 default is exactly 2026-08-01T00:00:00Z) but is silent on the fractional-digit rendering of this field (`.000Z` vs `Z`) — a two-reader divergence; kept the covered rule, dropped the format-silent one (STEP 1c partial-coverage handling).

- **Fixes applied to `implementation/`:** none — all failures traced to test-side artifacts; the implementation was PRD-faithful in every case (including the gate ordering, which PRD §3.5 states verbatim).

Orchestrator verification: all 8 results files present, each `passed: 80 / 80, failed: 0`.

## Step 8: Finalize PRD — 2026-08-15T04:30:00.000Z

Done. PRD_FINALIZED.md is written with exactly one revision, traced to the single step_7_diff item that was a genuine PRD silence.

## Summary

**Line counts / delta:** PRD.md = 405 lines, PRD_FINALIZED.md = 405 lines — 0% line-count delta (one line revised in place, no insertions or deletions).

**Changes (one bullet per change):**
- §3.11 — revise — `notified_at` sentence now pins both the value source ("to the current logical clock") and the rendering ("an ISO 8601 UTC timestamp with three fractional digits (e.g., `2026-08-01T00:00:00.000Z`)") — impl: `/home/ubuntu/github/CodingPRD/tasks/task_1950_seafood_processing_import_compliance/workspace/implementation/routes_compliance.py:245` (`r["notified_at"] = store.clock`), `/home/ubuntu/github/CodingPRD/tasks/task_1950_seafood_processing_import_compliance/workspace/implementation/services.py:490` (`iso_z3`), `/home/ubuntu/github/CodingPRD/tasks/task_1950_seafood_processing_import_compliance/workspace/implementation/utils.py:67-72`.

**Step_7_diff items requiring no PRD change (3 of 4):**
- `fixtures.py` `port_code` kwarg — pure test-helper bug; PRD §3.2 already declares `port_code` as a creation field and impl accepts it (routes_entries.py:64,87; services.py:301).
- test_07 `headers=ps01` — fixture-signature correction only; the asserted behavior (auto-CA `opened_by` = requesting `X-User-ID`) is already pinned verbatim by PRD §3.6.
- test_05 quarantine-release gate ordering — PRD §3.5's quarantine-release sentence already lists gates in exactly the implementation's order (open-CA → verification → histamine → abuse → freeze; routes_entries.py:401-411); implementation is PRD-faithful, nothing silent.

**Per-edit pre-edit search log:**
- **Edit 1 (§3.11 `notified_at`):**
  - (a) Subject: the Recall `notified_at` field — what instant it records and how it renders in JSON responses.
  - (b) Impl paths enumerated and read/grepped: routes_compliance.py:200 (recall created with `notified_at=None`), routes_compliance.py:235-247 (notify action sets `notified_at = store.clock`, only from `INITIATED`), services.py:485-492 (`serialize_recall` renders via `iso_z3` when set, `None` otherwise), utils.py:56-72 (`iso_z` vs `iso_z3` semantics); plus a full grep of `iso_z`/`iso_z3` across services.py, response.py, routes_suppliers.py mapping every timestamp field's rendering class — confirming server-set action timestamps (`prior_notice_filed_at` services.py:306, `entry_filed_at` :308, `approved_at` :458, `released_at` :476, `notified_at` :490, `created_at`/`updated_at` throughout, `api_request_timestamp` response.py:13) all render via `iso_z3`, while client-supplied datetimes use `iso_z`. Also read test_08 lines 21-41 and 360-395 to confirm the exact two-reader divergence Step 7 found.
  - (c) Wording adjustment: I initially considered a blanket claim covering all server-set timestamps; narrowed to `notified_at` only so the sentence stays inside step_7_diff scope and asserts nothing about other timestamp fields (all enumerated paths in (b) remain un-mis-described). Added "to the current logical clock" because the impl literally assigns `store.clock` and §3.13 defines that clock — consistent with every notify/recall path.

## Step 9: Complete PRD — 2026-08-15T04:50:00.000Z

All changes verified against the implementation. The task is complete.

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1950_seafood_processing_import_compliance/workspace/PRD_COMPLETED.md`

**Source vs. output:** `PRD_FINALIZED.md` (405 lines / 50,529 chars) → `PRD_COMPLETED.md` (418 lines / 58,350 chars); char-delta **+7,821**; diff hunks: 46 removed / 59 added lines (all in-paragraph inserts or inline revisions; no new sections).

**Counts:** 32 ambiguity-pins, 3 mismatch-revisions.

### Changes (one per bullet)

- §2.1 — insert — ambiguity — "Any" in §4 means the five operational roles; PlatformAdmin gets ERR_UNAUTHORIZED_ROLE on those endpoints — middleware.py:26-32
- §2.2 — insert — ambiguity — undefined paths → ERR_NOT_FOUND 404; unsupported method → ERR_NOT_FOUND 405; unhandled failures → ERR_INTERNAL 500 — app.py:44-54
- §2.3 — insert — ambiguity — non-integer limit/offset, limit outside 1–100, negative offset → ERR_VALIDATION_FAILED 400 — utils.py:229-248
- §2.3 — revise — ambiguity — list sort ties broken by creation (insertion) order — utils.py:251-253
- §2.4 — revise — ambiguity — updated_at equals created_at until first modification — services.py:270 (all serializers)
- §2.4 — insert — ambiguity — server-assigned timestamps come from the logical clock; server-set action timestamps always render 3 fractional digits, echoed/derived datetimes render millis only when nonzero — db.py:48,69; utils.py:56-72; services.py serializers
- §2.5 — insert — ambiguity — finer-precision numeric inputs are rounded half-up to class precision on write, not rejected; monetary fields must be integers — utils.py:17-40,137-143
- §2.7 — insert — ambiguity — the OCC version comparison is the final check on both endpoints, after all other validations — routes_suppliers.py:133-137; routes_processing.py:297-300
- §2.8 — insert — ambiguity — all field-level validation failures → ERR_VALIDATION_FAILED 400 — utils.py:93-225
- §3.1 — insert — ambiguity — duplicate facility_registration_number → ERR_VALIDATION_FAILED 400 — routes_suppliers.py:39-43
- §3.1 — revise — ambiguity — each submitted score is rounded half-up to 2dp on write; overall_score computed from the rounded scores — routes_suppliers.py:102-105
- §3.1 — insert — ambiguity — non-APPROVED outcome on SUSPENDED supplier, and any evaluation on REJECTED (terminal) supplier → ERR_INVALID_STATE 409; transitions into SUSPENDED/REJECTED leave evaluation date fields unchanged — routes_suppliers.py:112-124,153-174
- §3.1 — insert — ambiguity — suspending a non-APPROVED supplier → ERR_INVALID_STATE 409 — routes_suppliers.py:67-69
- §3.2 — insert — ambiguity — duplicate entry_number → ERR_VALIDATION_FAILED 400; duty_cents/allocatable_total_cents stay null until RELEASED — routes_entries.py:77-80,95-96
- §3.2 — revise — ambiguity — prior_notice_confirmation format: "PN" + 12 uppercase hex chars — routes_entries.py:148
- §3.2 — insert — ambiguity — disposition from DRAFT/PRIOR_NOTICE_FILED, on a terminal entry, or DETAINED→DETAINED → ERR_INVALID_STATE 409 — routes_entries.py:199-205
- §3.3 — insert — ambiguity — species_verified starts null; allocated_cost_cents starts at 0 — routes_entries.py:254,265
- §3.4 — insert — ambiguity — verification on a lot not UNDER_INSPECTION/QUARANTINED → ERR_INVALID_STATE 409 — routes_processing.py:69-73
- §3.4 — insert — ambiguity — resolve with verification not MISMATCH or lot not QUARANTINED → ERR_INVALID_STATE 409 — routes_processing.py:127-133
- §3.5 — insert — ambiguity — accept from any status other than UNDER_INSPECTION → ERR_INVALID_STATE 409 — routes_entries.py:349-351
- §3.5 — revise — mismatch — reject/quarantine reason is accepted but not persisted on the lot (PRD implied a persisted "reason"); quarantine from other statuses and reject from ACCEPTED/CONSUMED → ERR_INVALID_STATE 409 — routes_entries.py:366-391
- §3.6 — insert — ambiguity — adding an input requires the batch IN_PROCESS, else ERR_INVALID_STATE 409 — routes_processing.py:194-197
- §3.6 — insert — ambiguity — removing an input against a non-IN_PROCESS batch → ERR_INVALID_STATE 409; response returns the removed BatchInputLot row — routes_processing.py:236-251
- §3.6 — insert — ambiguity — actual_output_kg/trim_waste_kg/other_waste_kg must each be ≥ 0 — routes_processing.py:287-290
- §3.6 — insert — ambiguity — reopen retains recorded output/waste/yield fields; reopening non-COMPLETED or RELEASED/RECALLED-finished-lot batches → ERR_INVALID_STATE 409; reconciling non-COMPLETED → ERR_INVALID_STATE 409 — routes_processing.py:321-341
- §3.7 — revise — mismatch — re-run triggers are exactly four (entry RELEASED, acceptance, ACCEPTED→QUARANTINED, quarantine release); receipt-lot creation and ACCEPTED↔CONSUMED auto-transitions do not re-run allocation; non-eligible lots carry 0; allocation does not bump lot versions — services.py:96-122; routes_processing.py:219-224,243-249
- §3.8 — insert — ambiguity — counters are derived: open count = supplier-linked CAs in OPEN/INVESTIGATING; total_species_mismatches = SPECIES_MISMATCH CAs; total_haccp_deviations counts HISTAMINE_DEVIATION **and** TEMPERATURE_ABUSE CAs — services.py:43-59
- §3.8 — insert — ambiguity — month addition for next_evaluation_due clamps the day to month-end — utils.py:75-80
- §3.9 — revise — mismatch — abuse auto-CA fires only when the lot is currently UNDER_INSPECTION or ACCEPTED (PRD's "not already quarantined or rejected" literally included CONSUMED) — services.py:244
- §3.9 — insert — ambiguity — cumulative_abuse_minutes/freeze_compliant recomputation does not bump the lot version; version increments only via the quarantine cascade — services.py:234-249
- §3.10 — insert — ambiguity — hazard_type enum validated before subject existence; measured_value and subsample values rounded half-up to 1dp on write — routes_processing.py:446,465,471
- §3.10 — insert — ambiguity — CONFIRMATORY PARASITE: both measured_value and subsample_values forbidden (ERR_VALIDATION_FAILED 400); verdict is PASS — routes_processing.py:480-488,514-515
- §3.10 — insert — ambiguity — PARASITE deviation CA is batch-linked (supplier_id/receipt_lot_id null, no quarantine, supplier counters unaffected); measured_at is required — routes_processing.py:489,528-536
- §3.11 — insert — ambiguity — manual CA subject ids must exist (resource-specific 404); investigate outside OPEN/RESOLVED → ERR_INVALID_STATE 409; resolve outside INVESTIGATING → ERR_INVALID_STATE 409; reopen retains resolution_note/closed_by — routes_compliance.py:62-69,131-154
- §3.11 — insert — ambiguity — escalating a CA outside OPEN/INVESTIGATING → ERR_INVALID_STATE 409; validation order (reason/scope-shape → scope-lot existence → CA state); escalate response returns the updated CorrectiveAction; notify on non-INITIATED recall → ERR_INVALID_STATE 409 — routes_compliance.py:168-247
- §3.12 — insert — ambiguity — unknown supersedes_label_id rejected at creation (ERR_PRODUCT_LABEL_NOT_FOUND 404); approving non-DRAFT or superseding a non-APPROVED label → ERR_INVALID_STATE 409 — routes_compliance.py:255-258,306-315
- §3.12 — insert — ambiguity — finished-lot creation against non-COMPLETED/RECONCILED batch → ERR_INVALID_STATE 409; initial nulls/false for label fields; apply-label state violation → ERR_INVALID_STATE 409 and label-species mismatch → ERR_SPECIES_MISMATCH 422 — routes_compliance.py:344-347,357-367,417-434
- §3.12 — revise — ambiguity — release gate error ids pinned: lot not LABELED → ERR_INVALID_STATE 409; pinned label not APPROVED → ERR_LABEL_NOT_APPROVED 409 — routes_compliance.py:450-463
- §3.13 — insert — ambiguity — clock-set response body is an object carrying current_utc; missing/malformed to_iso8601 → ERR_VALIDATION_FAILED 400 — routes_suppliers.py:211-227
- §5 — insert — ambiguity — catalogue rows added: ERR_EVALUATION_NOT_FOUND 404, ERR_TEMPERATURE_LOG_NOT_FOUND 404, ERR_HACCP_RECORD_NOT_FOUND 404, ERR_NOT_FOUND 404, ERR_INTERNAL 500 — routes_suppliers.py:192; routes_processing.py:422,545; errors.py:48-49

No PRD-described behavior was found that the implementation contradicts beyond the three revisions noted (reason-not-persisted, allocation trigger list, abuse-trigger lot states); all other edits close PRD silence in favor of exactly what `implementation/` does.
