# Worklog — task_1579_building_information_model_coordination

## Step 1: Create Task Directory — 2026-08-13T23:09:00.000Z

Directory `tasks/task_1579_building_information_model_coordination/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per instructions.

## Step 2: Generate Scaffold — 2026-08-14T00:15:00.000Z

All artifacts are generated and lint-clean. Final report:

## Generated scaffold: task_1579_building_information_model_coordination

**Files written** (3,972 lines total):
- `/home/ubuntu/github/CodingPRD/tasks/task_1579_building_information_model_coordination/SCAFFOLD.yaml` (1,428 lines — §1.0–§1.7, no `scaffold_difficulty_design`/`scaffold_corner_design` keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1579_building_information_model_coordination/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (830 lines — single top-level key `scaffold_difficulty_design`)
- `/home/ubuntu/github/CodingPRD/tasks/task_1579_building_information_model_coordination/SCAFFOLD_CORNER_DESIGN.yaml` (1,714 lines — single top-level key `scaffold_corner_design`)

**Counts (maximal / beyond-expert calibration):**
- Entities: **16** (Project with parallel phase × posture dimensions, LodRequirement, TradePartner, TradeModel with self-referential supersedes FK, FederatedModel, FederatedModelMember junction, FreezeWindow, ClashDetectionRun, ClashIssue, CoordinationMeeting, ResolutionCommitment, FabricationPackage, SignOff, AsBuiltModel, QuantityTakeoff, HandoverPackage)
- State machines: **14** entries — cyclic (ClashIssue VERIFIED→REOPENED→ASSIGNED loop, TradeModel rework loop, HandoverPackage FM-rejection loop, SignOff re-request loop), parallel dimensions (Project phase × posture), compound (FederatedModel DRAFT→ASSEMBLED bubble-up, FabricationPackage auto-READY), plus 2 OCC concurrency rules on `Project.version`
- Calculations: **14** — including dual variants on three entity domains (clash provisional-vs-actual cost, model submission-vs-audit score, gross-vs-net takeoff) and all three combinatorial modes: (a) multi-input CRI threshold blend, (b) pinned per-element-then-sum rounding, (c) pre-event-tier reliability evaluation order
- Validations: **12** priority rows (auth → ownership → existence → request-shape → OCC → state → safety → referential → constraint → temporal → fiscal)
- Endpoints: **72** (flat `/api/...` scheme so every FK has lint-checkable reverse-reachability; includes `POST /api/_clock/set_current_utc` with the mandated `2026-08-01T00:00:00Z` default)
- Errors: **70**, all referenced by validations/transitions and covered by ≥1 design instance
- Roles: **6** — segregation-of-duties model (VDCManager, BIMCoordinator, entity-backed TradeModelAuthor and FabricationLead, LeadEngineer with sign-off SoD vs. model submitter, FacilitiesManager), with two SoD conflict errors
- **§1.8: 19 instances** across all 9 difficulty rules (≥2 each; `combinatorial_formula` has 3, one per mode), every instance with a fully structured `setup_api_calls`/`trigger`/`assert` chain replayable from empty-DB, literal-computed assert values (e.g., provisional 720000 vs actual 258000 cents; CRI 45/75/85; reliability walk 100→65; NET 0.248 vs GROSS 0.247)
- **§1.9: 71 instances** (60 active with test recipes + 11 `excluded_because` stubs citing §1.8 instances) spanning all nine claim-extraction-guide sections, including every error code's trigger, RBAC denials, ownership checks, SoD probes, OCC stale-version tests, pagination/envelope checks, and terminal lockdowns

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(72 endpoints, 16 entities, 19 §1.8 + 60 §1.9 active instances, 1,035 calls scanned.)

Post-lint mechanical checks also passed: no instance-name collisions across both design files (90 names), zero unbound `${var}` placeholders, zero unresolvable `grounds:` references, all stub citations resolve to real §1.8 instances, no forbidden concurrency vocabulary, and enum-value closure holds (PROBATION is produced by the `trade_partner_reliability` calculation output).

## Step 3: Copy Shared Files — 2026-08-14T00:17:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1579_building_information_model_coordination/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T00:36:00.000Z

The PRD is generated and all audits pass. Summary of what was produced:

## Generation Summary

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1579_building_information_model_coordination/workspace/PRD.md` — 372 lines, 8,287 words.

### Section structure
- **§1 Introduction** — 2 paragraphs (business-context angle, system-goal angle)
- **§2 Global Specifications** — 10 subsections: 2.1 RBAC (6 roles, entity-backed vs opaque identity translation), 2.2 API Response Structure (emitted **verbatim** from `section-2.2-response-structure.md`), 2.3 Pagination (limit default 10/min 1/max 100, offset 0, created_at ascending), 2.4 Common Resource Properties, 2.5 The Logical Clock (initial 2026-08-01T00:00:00Z, monotonic, no auto-breach), 2.6 Coordination Readiness & Posture (full CRI formula: 25/10/5/15 weights, floor 0, hold thresholds 60, probation-partner clause), 2.7 Version Pinning & Staleness Propagation, 2.8 Validation Order & Hierarchical Resolution (all 12 priority layers in explicit order, 13 not-found IDs, left-to-right path resolution), 2.9 OCC (both guarded creates, `expected_project_version`, `ERR_STALE_PROJECT_VERSION` 412), 2.10 Units/Precision/Rounding (mm 1dp, scores 1dp half-up, integer cents, quantities 3dp decimal)
- **§3 Business Logic** — 8 subsections organized chronologically by project lifecycle: 3.1 Project setup/phases/partner onboarding, 3.2 Trade model authoring + full interop matrix + submit/accept gates + CASCADE A (4 links + bubble-up), 3.3 Federated assembly/freeze/release + freeze-window gap rule (closed intervals, 3,600s buffer), 3.4 Clash runs + full clash cycle (severity 50.0 mm boundary, provisional vs actual cost dual variant, budget gate, SoD verify, reopen cascade B, fulfill cascade C), 3.5 Meetings/commitments/reliability decay (half-open room overlap, sweep ordering, tier-from-pre-event-score), 3.6 Fabrication packages + sign-off SoD + release gates (CRI ≥ 85, phase, posture), 3.7 As-builts + quantity extraction (GROSS vs NET rounding order), 3.8 Handover to facilities
- **§4 Endpoint table** — 72 rows, 4 columns (Method/Path/Description/Authorized Role)
- **§5 Error catalogue** — 70 rows, 2 columns (Error ID/HTTP Status), exact statuses incl. 402/412/422 variants

### Coverage audit results
```
Contract 1 (Field coverage, 2 passes run):
- entities[].fields: 93 required, 93 present, 0 missing
- endpoints[] request_body/query extras: 9 required, 9 present, 0 missing
- common fields: 4 required, 4 present, 0 missing — PASS
Contract 2 (Rule coverage, manual walk): all 14 state machines' transitions with
  preconditions+error IDs+side effects, all 14 calculations with constants/boundaries,
  12-layer validation priority order stated explicitly, both OCC rules with
  endpoint+field+error+status, all applies_to scopes enumerated, CASCADE A/B/C fully
  expanded, sibling branches (4 federated-supersede states, verify dual outcome,
  GROSS/NET, ACCEPT/REJECT) at equal density — PASS
Contract 3 (§3 path purity): 569 backtick tokens scanned, 0 '/'-prefixed, 0 bare
  HTTP methods, 0 method+path tokens — PASS
Auxiliary: 70/70 error IDs mentioned in §1-§4 prose; 72/72 enum/state values present
  verbatim; 0 fuzzy words; 0 pseudocode operators in §3; §2.2 byte-verbatim — PASS
```

### Key decisions
- §2 subsection titles are domain-derived (Logical Clock, Version Pinning & Staleness, Coordination Readiness & Posture) rather than template names; §3 uses a chronological lifecycle grouping (8 subsections).
- OCC parameters (`expected_project_version`) are specified in §2.9 while the rest of those two creates' parameters live in §3.3/§3.7, satisfying the ≥2-subsection scattering rule.
- One repair during audit: `fabrication_package_id` was missing; added to the §3.6 sign-off creation sentence, then re-ran to PASS.
- One scaffold gap handled without invention: commitment creation requires the clash to be `ASSIGNED` but the scaffold nominates no error ID for that check — the PRD states the requirement in prose without fabricating an error code.
- The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened or referenced.

## Step 5: Generate Unit Tests — 2026-08-14T01:45:00.000Z

Generation complete and fully audited. Summary:

## Test counts

**Queue A (Difficulty, §1.8): 38 tests covering 19/19 instances at exactly 2 tests each** — dual_variant_calc (2), combinatorial_formula (3), non_linear_state_machine (2), transitive_cascade (2), priority_pair_validation_conflict (2), boundary_precision_check (2), cross_entity_state_dependency (2), resource_temporal_overlap (2), compensating_invariant (2).

**Queue B (Corner, §1.9): 59 tests covering 59/60 non-stub instances at 1 test each.** All 11 `excluded_because` stubs left untranslated; every stub's `difficulty_instance` cross-reference resolves.

**Total: 97 tests** across 8 files (`test_01` project setup/auth/RBAC/not-found, `test_02` trade models/interop/scores, `test_03` federated assembly/OCC/version pinning/freeze windows, `test_04` clash runs/resolution cycle, `test_05` CRI/posture/reliability/release gates, `test_06` meetings/commitments, `test_07` fabrication packages/sign-offs/takeoffs, `test_08` as-built/handover).

## Instances skipped (with reason)

- `Corner/validations/asbuilt_and_handover_phase_gates_rejected` — its handover mark-ready probe asserts `ERR_PHASE_REQUIREMENT_NOT_MET` under a multi-gate failure (phase + takeoff-not-approved + no as-builts), but PRD §2.8's fixed order places "handover aggregate gates" (Tenth) before "phase timing gates" (Eleventh) with first-failure-wins semantics — the PRD-derived outcome is an aggregate-gate error. The asserted outcome contradicts the PRD (not merely underdetermined), so the instance fails unique-derivability. Gap left as a gap.

## Helper files written

`test_helpers/`: `types.py`, `api_client.py` (72 endpoints under `/api`), `api_errors.py` (69 ids + framework-registered HTTP map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque constants + entity-backed builders), `fixtures.py` (five-tier composites), `__init__.py` barrel. `test_suite/conftest.py` bridges fixtures.

## Translation notes (judgment calls, all PRD-anchored)

- Three design recipes record a commitment *after* resolving its clash; PRD §3.5 requires the clash `ASSIGNED` at commitment creation, so the commitment step was moved before the resolve step (asserted outcomes unchanged).
- `assign_safety_beats_referential_on_dual_violation`'s yaml annotation says reliability 35 after nine swept breaches; the PRD-pinned tier walk yields 25 (45 is tier C → −20). The test asserts the PRD-derived 25.
- Three `validate_error_is_one_of` relaxations where the PRD fixes no precedence: package release on a non-existent id (404 vs 403), package create scope-absent vs assembly-unfrozen dual failure, handover mark-ready's sibling aggregate gates.

## Stage-2 audit results

- Coverage: queue A 19/19 (≥2 each), queue B 59/60 + 1 documented skip; no untagged/dual-tagged/dangling tags (C4 verified mechanically against both yamls).
- Citations: all 167 quoted PRD segments survive literal whitespace-normalized grep of `workspace/PRD.md`; every asserted error id (69 distinct) appears in §2/§3 prose, not just §5.
- No `skip`/`skipif`/`xfail` markers; no scaffold references in generated code; pyflakes clean (undefined/unused); pytest collects 97.

## Live verification

Ran the suite under `prd-bench-local-run --isolation per-test-server` against the existing `workspace/implementation`: **95/97 pass**. The 2 failures are genuine PRD §2.8 fixed-validation-order deviations in the implementation, asserted exactly as the design instances intend: (1) clash-assign dual violation returns `ERR_CROSS_PROJECT_REFERENCE` where the Eighth-layer probation bar must fire first (`ERR_TRADE_PARTNER_ON_PROBATION`); (2) handover respond with out-of-range `decision` on a READY package returns `ERR_HANDOVER_NOT_TRANSMITTED` where the Fifth-layer shape check must fire first (`ERR_INVALID_REQUEST`). Both tests kept — they encode the PRD-pinned order and flag real conformance bugs.

## Step 6: Generate Implementation — 2026-08-14T00:51:00.000Z

(Completed while Step 5 was still running; recorded here in launch-order position per pipeline sequence — Steps 5 and 6 were launched concurrently.)

All cascade behavior works correctly. The implementation is complete.

## Summary

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1579_building_information_model_coordination/workspace/implementation/start.sh` — foreground bash launcher, guards `pip install` behind `python3 -c "import flask"`, then `exec python3 app.py`
- `/home/ubuntu/github/CodingPRD/tasks/task_1579_building_information_model_coordination/workspace/implementation/requirements.txt` — `flask>=3.0`
- `/home/ubuntu/github/CodingPRD/tasks/task_1579_building_information_model_coordination/workspace/implementation/app.py` — single-module Flask app (~1400 lines)

**Endpoint count:** 72 endpoints (full §4 table): project CRUD + phase + sweep, LOD requirements, trade partners, trade models (create/list/get/submit/accept/reject), federated models (create/list/get/freeze/unfreeze/release + members + by-model memberships), freeze windows, clash runs (create/list/get/start/import/complete), clash issues (list/get/assign/resolve/verify/reopen), meetings (create/list/get/start/adjourn), commitments (create/list/get/waive), fabrication packages (create/list/get/submit-for-signoff/release/void + sign-offs list), sign-offs (get/sign/decline + by-model list), as-built models (create/list/get/submit/verify), quantity takeoffs (create/list/get/approve), handover packages (create/list/get/mark-ready/transmit/respond), and `POST /api/_clock/set_current_utc`.

**State machines** are implemented inline per endpoint with explicit from-state guards producing the exact scaffold `error_id`s (e.g., `ERR_MODEL_NOT_SUBMITTABLE`, `ERR_FED_NOT_ASSEMBLED`, `ERR_PACKAGE_NOT_RELEASABLE`). Cyclic machines (ClashIssue reopen loop, SignOff re-request, FULFILLED→BREACHED commitments) are supported. Cascade A (accept-time supersede → member re-point → FROZEN→ASSEMBLED unfreeze with `is_stale=true` → SIGNED sign-off revocation → READY_FOR_RELEASE→SIGNOFF_IN_PROGRESS regression → DRAFT-fed bubble-up), Cascade B (reopen → fulfilled commitments breached → reliability decay → probation), and Cascade C (verify → commitment fulfill) are factored as helper functions (`cascade_on_accept`, `unfreeze_fed`, `revoke_signed_signoffs_for_fed`, `breach_commitments_for_clash`, `fulfillments_for_clash`).

**Calculations** use `decimal.Decimal` with `ROUND_HALF_UP` per §2.10: interop matrix lookup, clash severity (50.0 mm strict-greater boundary), provisional cost (severity-based 40/16/4 base × 1.5 spans × partner rate, integer cents), actual cost (claimed hours × current partner rate, no spans multiplier), element-weighted submission score (1 dp), criticality-weighted audit score (0.5/0.3/0.2 with renormalization, 1 dp), GROSS vs NET takeoff totals (NET rounds per-element at 3 dp then sums, no second rounding), CRI (25/10/5/15 weights floored at 0), posture derivation (CRI < 60 OR probated partner with open assigned clash), tiered reliability decay (tier read from pre-breach score: ≥80→5, ≥50→10, else 20; probation at <40), half-open meeting overlap (adjacency allowed), closed-interval freeze-window 3600s gap (boundary 3600 allowed), 25.0 mm as-built tolerance.

**Validations** are ordered per §2.8 twelve-layer sequence: auth headers → role → entity-backed ownership → path/body existence → request shape → OCC (on federated-models and quantity-takeoffs creates only, `expected_project_version`, before business rules) → from-state → compliance/SoD/posture gates → cross-project referential integrity → aggregate/uniqueness → temporal → fiscal budget (last).

**Boot check:** Confirmed clean boot from a fresh process across two consecutive `bash start.sh` invocations — the second boot returns `ERR_PROJECT_NOT_FOUND` for entities created during the first boot (no carry-over state), and a fresh project created on the second boot starts at `version: 1`. Smoke tests exercised: project creation, LOD uniqueness, trade-model lifecycle (DRAFT→SUBMITTED→ACCEPTED), OCC 412, fed freeze/release with open-clash gate, clash import → assign → resolve → verify (provisional 900000 / actual 450000 cents verified), NET takeoff rounding (per-element → 14.000), takeoff approve, clock advance + backward rejection, meeting room adjacency/overlap, invalid time-range 422, and the full Cascade A sign-off revocation/regression chain.

## Step 5 (addendum, self-recorded by the Step 5 subagent): Generate Unit Tests — 2026-08-14T02:00:00.000Z

Design-index-only translation: every test carries exactly one `Design: Difficulty/<rule_id>/<instance>` or `Design: Corner/<section>/<instance>` docstring tag copied verbatim from the source yaml.

**Files written:**
- `test_helpers/`: `types.py` (16 entity TypedDicts + 15 status/role enums), `api_client.py` (72 endpoint methods, `/api` prefix), `api_errors.py` (69 error ids + HTTP map registered with the framework), `assertions.py` (per-entity + run-counter conservation invariant), `factories.py`, `constants.py` (CRI weights 25/10/5/15, thresholds 60/85, tariff 40/16/4 × 1.5, reliability tiers 80/50 with penalties 5/10/20, probation at 40, 50.0 mm / 25.0 mm / 3600 s), `test_users.py` (6 roles; entity-backed builders for TradeModelAuthor/FabricationLead), `fixtures.py` (five-tier composite chains incl. `setup_running_run`, `setup_ready_package`, `setup_partner_with_reliability`, `setup_probation_partner_via_reopen`, `setup_closeout_project_with_verified_asbuilt`), `__init__.py` barrel.
- `test_suite/`: `conftest.py` + 8 numbered test files, 97 tests.

**Coverage:** Queue A 19/19 instances × ≥2 tests (38). Queue B 59/60 non-stub instances × 1 test (59); 11 `excluded_because` stubs untranslated (all difficulty-instance cross-references resolve).

**Skipped instance (PRD-first filter):** `Corner/validations/asbuilt_and_handover_phase_gates_rejected` — its handover mark-ready probe asserts `ERR_PHASE_REQUIREMENT_NOT_MET` under a dual failure (phase SCHEMATIC_DESIGN + takeoff EXTRACTED + zero as-builts), but PRD §2.8's fixed layer order puts "the handover aggregate gates" (Tenth) before "phase timing gates" (Eleventh) with first-failure-wins semantics, so the PRD-derived outcome is an aggregate-gate error, not the asserted phase error. The instance's asserted outcome contradicts the PRD → skipped per the Core rule (gap left as a gap).

**Sanctioned `validate_error_is_one_of` relaxations (PRD-silent precedence):** package release on a non-existent id (404 vs ownership 403); package create with scope-absent + assembly-unfrozen dual failure; handover mark-ready with takeoff-unapproved + open-clash sibling aggregate gates (same layer, no PRD order).

**Design-recipe repair (not weakening):** three recipes record a commitment after resolving its clash; PRD §3.5 requires the clash to be `ASSIGNED` at commitment creation, so the commitment step was moved before the resolve step in `test_verify_failed_measurement_reopens_clash`, `test_verify_at_exact_tolerance_verifies`, and `setup_probation_partner_via_reopen`. All asserted outcomes unchanged.

**Design-yaml value correction:** `assign_safety_beats_referential_on_dual_violation`'s setup check annotated reliability 35 after nine swept breaches; the PRD-pinned walk (100→95→90→85→80→75→65→55→45→**25**, tier C −20 from pre-event 45) yields 25, which the test asserts (35 is unreachable under §3.5).

**Execution under `prd-bench-local-run --isolation per-test-server`:** 95/97 pass (125 s). The 2 failures are genuine PRD §2.8 validation-order deviations in the shipped implementation, asserted exactly as the design instances intend: (1) assign dual-violation returns `ERR_CROSS_PROJECT_REFERENCE` where the Eighth-layer probation bar must fire first (`ERR_TRADE_PARTNER_ON_PROBATION`); (2) handover respond with out-of-range `decision` on a READY package returns `ERR_HANDOVER_NOT_TRANSMITTED` where the Fifth-layer shape check must fire first (`ERR_INVALID_REQUEST`, cf. §3.8 "any other decision value"). Tests kept as-is — they encode the PRD-pinned order.

**Static audits:** 97 tests collected; every docstring carries verbatim PRD citations (167 quoted segments grep-verified against PRD.md) + exactly one terminal Design tag; no skip/xfail markers; no scaffold references in generated code; all 69 asserted error ids appear in PRD §2/§3 prose.

## Step 7: Run Tests and Iterate — 2026-08-14T02:10:00.000Z

Subagent returned: All 8 parallel rounds pass cleanly (97/97 each). The loop is complete.

## Summary

- **Iterations run:** 2 sweeps (baseline 8-round sweep to verify the 2 known failures deterministically; 1 post-fix 8-round sweep — all 8 rounds 97/97, zero failures, zero flakiness).

- **Tests deleted:** None. Both failing tests passed STEP 1 (PRD §2.8 states the twelve-layer fixed validation order verbatim: "rejected at the first layer it fails", with the probation bar named in the Eighth layer and same-project referential integrity in the Ninth; shape checks with enum-range failures as `ERR_INVALID_REQUEST` in the Fifth layer, from-state legality in the Seventh) and STEP 2 (setups, requests, and assertions faithfully express the cited PRD rules, with verbatim §2.8/§3.4/§3.8 citations in the docstrings).

- **Fixes applied to `test_helpers/`:** None.

- **Fixes applied to `implementation/`** (both in `/home/ubuntu/github/CodingPRD/tasks/task_1579_building_information_model_coordination/workspace/implementation/app.py`):
  1. `assign_clash` (~line 1619) — reordered checks so the probation bar (`ERR_TRADE_PARTNER_ON_PROBATION`, PRD §2.8 Eighth layer: "the probation bar at clash assignment") fires before the same-project referential check (`ERR_CROSS_PROJECT_REFERENCE`, Ninth layer). Fixes `test_assign_safety_beats_referential_on_dual_violation`.
  2. `respond_handover` (~line 2481) — moved the `decision` enum-range shape check (`ERR_INVALID_REQUEST`, Fifth layer: "enum values within range", cf. §3.8 "any other decision value is `ERR_INVALID_REQUEST`") before the from-state check (`ERR_HANDOVER_NOT_TRANSMITTED`, Seventh layer). Fixes `test_handover_full_cycle_with_facilities_rejection_loop`.

- **Result:** 8/8 rounds × 97/97 tests passed (776/776 executions). No assertion weakened, no check removed, no capability added beyond PRD.

### Step 7 loop detail (self-recorded by the Step 7 subagent)

Fresh 8-round parallel sweep confirmed the 2 known failures deterministically (8/8 rounds each, no flakiness). Both were implementation deviations from PRD §2.8's fixed twelve-layer validation order; both tests kept as-is (PRD-faithful, verbatim citations).

**Implementation fixes (app.py):**
1. `assign_clash` — moved the probation bar (`ERR_TRADE_PARTNER_ON_PROBATION`, §2.8 Eighth layer) ahead of the same-project referential check (`ERR_CROSS_PROJECT_REFERENCE`, §2.8 Ninth layer).
2. `respond_handover` — moved the `decision` enum shape check (`ERR_INVALID_REQUEST`, §2.8 Fifth layer) ahead of the from-state check (`ERR_HANDOVER_NOT_TRANSMITTED`, §2.8 Seventh layer).

Post-fix 8-round parallel sweep: 97/97 passed in every round (776/776 total test executions, 0 failures, 0 errors). No tests deleted; no test_helpers changes.

## Step 8: Finalize PRD — 2026-08-14T02:20:00.000Z

Done. PRD_FINALIZED.md is written with exactly two inline pins, both tracing to the Step 7 implementation fixes.

## Summary

**Line counts**: PRD.md = 372 lines; PRD_FINALIZED.md = 372 lines (0.0% line-count delta; 2 lines revised in place, ~90 words added total).

**Changes** (one bullet each):

- §3.4 (clash assignment paragraph) — revise — appended a dual-violation ordering pin: when the named partner is both on probation and foreign to the project, the §2.8 fixed layer order makes the probation bar (Eighth layer) precede the same-project referential check (Ninth layer), so the rejection is `ERR_TRADE_PARTNER_ON_PROBATION` — `implementation/app.py:1621-1624` (fix site ~1619).
- §3.8 (handover respond sentence) — revise — appended a shape-vs-state ordering pin: the `decision` enum rule is Fifth-layer request shape under §2.8 and is evaluated before the Seventh-layer from-state requirement, so an out-of-range `decision` draws `ERR_INVALID_REQUEST` even when the package is not `TRANSMITTED` — `implementation/app.py:2484-2488` (fix site ~2481), `HANDOVER_DECISIONS = ["ACCEPT", "REJECT"]` at `app.py:42`.

**Why edits despite §2.8 already ordering the layers**: §2.8 does determine both orderings abstractly, but the §3.4/§3.8 narratives mention the checks in the opposite prose order — the original implementation followed that prose order and Step 7 had to correct both sites. The pins eliminate the proven misreading without altering any §2.8-determined behavior.

**Per-edit pre-edit search log**:

1. Edit 1 (§3.4):
   - (a) Subject: relative order of the probation bar vs the same-project referential check at clash assignment.
   - (b) Paths enumerated: grepped `ERR_TRADE_PARTNER_ON_PROBATION`, `ERR_CROSS_PROJECT_REFERENCE`, `PROBATION` across `app.py`. Probation bar is single-site (`assign_clash`, line 1622; probation transitions otherwise only at lines 355/580-581 in reliability logic, unrelated to request validation). Cross-project check has 8 sites (lines 1060, 1227, 1624, 1856, 1949, 2186, 2311, 2401) but only `assign_clash` pairs it with a probation bar. Also read `resolve_clash`/`verify_clash`/`reopen_clash` (1639-1734) to confirm no parallel probation interaction. Tests `test_assign_safety_beats_referential_on_dual_violation` and `test_assign_cross_project_only_violation` confirm expected dual- and single-violation outcomes.
   - (c) Wording scoped to "when the named partner violates both of these rules at once" — deliberately avoids any universal claim about full check ordering at assignment (the impl checks from-state before body-reference existence there, which my sentence does not touch) and about other endpoints' referential checks.

2. Edit 2 (§3.8):
   - (a) Subject: relative order of the `decision` enum-range shape check vs the `TRANSMITTED` from-state check at handover respond.
   - (b) Paths enumerated: grepped `HANDOVER_DECISIONS`, `ERR_HANDOVER_NOT_TRANSMITTED`, `decision` across `app.py` — both are single-site at `respond_handover` (2477-2492); missing `decision` also yields `ERR_INVALID_REQUEST` (None not in list), consistent with §2.8 "required fields present". Verified no other endpoint takes a `decision` field. Noted `resolve_clash` checks from-state before its hours shape check — so the wording was kept operation-local rather than claiming a universal shape-before-state rule.
   - (c) Wording scoped to the respond operation ("a response whose `decision` falls outside `ACCEPT`/`REJECT` ... even when the package is not `TRANSMITTED`"), matching the impl exactly and making no claim about other endpoints.

No tests were read as alignment targets; implementation behavior is the sole source of both pins.

## Step 9: Complete PRD — 2026-08-14T02:40:00.000Z

All edits applied. Summary of the completed work:

## Summary

**Source vs output:** `PRD_FINALIZED.md` (372 lines, 61,957 chars) → `PRD_COMPLETED.md` (372 lines, 63,625 chars). Char-delta: +1,668. Line count unchanged (all edits are inline insertions/revisions within existing paragraphs; no new sections).

**Counts:** 11 ambiguity-pins, 4 mismatch-revisions (15 changed passages total; 14 edits, one of which spans two layers of §2.8).

### Ambiguity pins (11)

- §2.1 — insert — ambiguity — a role value outside the six recognized roles is rejected with `ERR_UNAUTHORIZED_ROLE` — implementation/app.py:277-278
- §2.3 — insert — ambiguity — out-of-range/unparseable `limit`/`offset` are coerced (limit clamped to [1,100], negative offset to 0, non-integer to defaults) rather than rejected — implementation/app.py:292-307
- §2.3 — insert — ambiguity — list sort ties on creation timestamp are broken by `id` — implementation/app.py:308
- §2.9 — insert — ambiguity — on the two OCC-guarded creates, the version check runs after Fifth-layer shape validation but before body-reference resolution, so a stale version yields `ERR_STALE_PROJECT_VERSION` even when a referenced member/federated model does not exist — implementation/app.py:1210-1223, 2303-2309
- §3.3 — insert — ambiguity — `member_trade_model_ids` must be a non-empty array; absent/empty/non-array is `ERR_INVALID_REQUEST` — implementation/app.py:1205-1207
- §3.4 — insert — ambiguity — a negative `re_inspection_overlap_mm` is a shape failure (`ERR_INVALID_REQUEST`) — implementation/app.py:1686-1688
- §3.4 — revise — ambiguity — verify fulfillment cascade applies to *every* linked `COMMITTED` commitment (not just one) — implementation/app.py:737-747
- §3.4 — revise — ambiguity — reopen breach cascade applies to *every* linked `FULFILLED` commitment — implementation/app.py:756-764
- §3.5 — insert — ambiguity — commitment creation against a clash not currently `ASSIGNED` is rejected with `ERR_CLASH_NOT_ASSIGNABLE` — implementation/app.py:1852-1853
- §3.6 — insert — ambiguity — package creation by a caller that is not an existing trade partner of the project is rejected with `ERR_FORBIDDEN_OWNERSHIP` (covers both unknown and cross-project caller ids) — implementation/app.py:1941-1944
- §3.6 — insert — ambiguity — a sign-off re-request changes only status; recorded `trade_model_id`/`pinned_model_version` pins are not refreshed — implementation/app.py:2038-2045

### Mismatch revisions (4)

- §2.8 (Seventh layer) — insert — mismatch — impl evaluates the from-state check (and, at clash verify, the SoD gate) *before* Fifth-layer body-shape rules on clash resolve, clash verify, and as-built verify, contrary to the strict numeric layer order — implementation/app.py:1648-1652, 1682-1688, 2250-2251
- §2.8 (Eleventh layer) + §3.6 — revise — mismatch — package-release gate order is state → fed `FROZEN`/`RELEASED` → phase → posture → CRI (PRD had posture → CRI → phase); §3.6 now enumerates the impl order and §2.8 carries the rider — implementation/app.py:2057-2072
- §2.10 — revise — mismatch — client timestamps are compared exactly as supplied at full precision; impl's `parse_iso` does not truncate to seconds despite the PRD claiming second-precision comparison — implementation/app.py:219-236
- §3.5 — revise — mismatch — a coordination sweep advances the project `version` by two (recompute mutation + `ops_sweep_index` increment each `touch` the project), not "by one" as the PRD stated — implementation/app.py:922-924

Everything else in the implementation — the interop matrix, severity boundaries, submission/audit score formulas, CRI blend and posture rules, supersession/unfreeze/revocation cascades, freeze-window gap arithmetic, meeting half-open conflict rule, reliability tiers, takeoff rounding orders, handover gates, error catalogue statuses, endpoint table and role assignments — was verified to match the PRD as written and required no change.
