# Worklog — task_2494_artificial_intelligence_governance_model_approval

## Step 1: Create task directory — 2026-09-03T00:00:00.000Z

Created `tasks/task_2494_artificial_intelligence_governance_model_approval/` and `tasks/task_2494_artificial_intelligence_governance_model_approval/workspace/`. Index pre-assigned by the orchestrating harness (2494); no index allocation scan performed, per instructions (32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-03T02:40:00.000Z

All three artifacts are complete and lint-clean.

## Verdict block (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2494_artificial_intelligence_governance_model_approval/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2494_artificial_intelligence_governance_model_approval/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2494_artificial_intelligence_governance_model_approval/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    50
  §1.1 entities declared:     12
  §1.8 instances scanned:     18
  §1.9 instances scanned:     69
  Calls scanned (§1.8+§1.9):  771

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files

- `SCAFFOLD.yaml` (3162 lines) — top-level keys are only §1.0–§1.7 (`scenario`, `domain_name`, `api_prefix`, `complexity_profile`, `difficulty_level`, `response_envelope`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles`); no design keys. `scenario` is byte-verbatim.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (661 lines) — single key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` (1692 lines) — single key `scaffold_corner_design`.

## Scale

12 entities, 10 state machines, 2 concurrency rules, 11 calculation rules (2 carrying divergent variants), 41 prioritized validations, 50 endpoints, 39 error codes, 6 roles. `difficulty_level: expert_plus`; layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `version_pinning_on_approval`; flat topology, cyclic state machines, segregation-of-duties role model, immediate consistency, `api_prefix: ""`.

## §1.8 coverage — all 9 rule_ids, 18 instances (2 each)

`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

## §1.9 coverage — all 9 sections, 87 instances (69 live recipes + 18 `excluded_because` stubs)

entities 10/0, state_machines 7/2, calculations 6/8, validations 5/0, endpoints 6/0, errors 20/6, rbac 10/0, cross_cutting_layers 3/2, consistency_model 2/0. All 39 error codes are mapped in the header comment; every stub cites an existing §1.8 instance (normalized to the `rule_id / instance_name` form from SKILL.md); no name collides across the two design files.

## Design adjudications

- **`ERR_APPROVAL_EXPIRED` reachability (structural fix to SCAFFOLD.yaml).** Because `approve` sets `reassessment_due_at == approval_expires_at`, any sweep that opens a reassessment does so at an instant already `>=` the expiry. Validation p40 originally read `now < approval_expires_at`, which made *both* `complete-reassessment` outcomes permanently unreachable. p40 is now inclusive (`now <=`, with the reasoning inline) and the catalog condition reads "strictly after"; the error stays reachable by sweeping at exactly the expiry instant, then advancing the clock without a second sweep.
- **Sweep comparison semantics fixed** to `now >= reassessment_due_at` (inclusive), `now > approval_expires_at` and `now > grace_deadline_at` (strict), so the two SUSPENDED transitions and the shadow-enforcement step are each independently reachable.
- **RBAC claim types stay inside the guide's vocabulary.** The guide's RBAC section has no authentication row, so a planned `rbac_missing_x_user_id_header_unauthenticated` instance was dropped and `ERR_UNAUTHENTICATED` moved to `validations / unauthenticated_precedes_not_found` (blank `as_user_id`, ordered against a 404). Three distinct denial codes are kept separate: `ERR_UNAUTHORIZED` (role absent from the endpoint), `ERR_GATE_ROLE_MISMATCH` (role present but wrong `gate_type`), `ERR_SEGREGATION_OF_DUTIES` (right role, disqualified identity — both limbs: requester-clears-own-gate and clearer-signs-approval).
- **`PROHIBITED`-band fixture uses `CONFIDENTIAL` sensitivity** (score 99) so it does not trip `PROHIBITED_COMBINATION`; the row survives in `UNDER_REVIEW`, which is what makes `ERR_PROHIBITED_USE_CASE` observable on a binding attempt.
- **Two reusable chains** keep the 771 calls consistent: a 15-call MIN-APPROVED chain (final score 7, MINIMAL, 730-day interval, expiry 2028-07-31 — leap-year arithmetic) and an 18-call LIMITED "Chain A" (provisional 49, control credit 8, final 41, 365-day interval, expiry 2027-08-01).
- **Boundary literals are pre-computed**, e.g. BIAS at exactly `0.7000` with `sample_size` exactly `300` (both `>=`), SEV1 containment at `2026-08-01T04:00:00Z`, MINIMAL BUSINESS gate debt `0.75 * (2/3) * 0.5 = 0.25` released to `0.00` with ledger `debt_delta -0.25`.
- **Both `concurrency_rules` get their own live instance** using `expected_use_case_version: "${var} - 1"`, plus a positive control that shows the version bump.

## Step 3: Copy shared files — 2026-09-03T02:41:00.000Z

Copied `./INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T02:57:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md`

## Document

- **479 lines**, 28 headings, assembled from six staged parts and concatenated in one pass (no truncation).
- **Sections:** Title; §1 Introduction; §2 Global Specifications (11 subsections: 2.1 Role-Based Access Control, 2.2 API Response Structure, 2.3 Pagination, 2.4 Record Identity/Timestamps/Row Versions, 2.5 The Logical Clock, 2.6 Version Pinning and Stale-Version Rejection, 2.7 Scoring Precision and Rounding Discipline, 2.8 Path Resolution and Reference Integrity, 2.9 Order of Evaluation for Rejections, 2.10 Cascade Discipline and Derived Counters, 2.11 The Governance Ledger and Conserved Quantities); §3 Business Logic (9 subsections: 3.1 Model Asset Registry & Vendor Terms Grading, 3.2 Intake/Provisional Classification/Revision Loop, 3.3 Gate Review by the Four Domain Reviewers, 3.4 Binding a Model & Exclusive Test Windows, 3.5 Designing Human Oversight, 3.6 Statutory Disclosure Notices, 3.7 Signing the Deployment Approval, 3.8 Post-Deployment Monitoring/Suspension/Reinstatement/Revocation, 3.9 Periodic Reassessment/Shadow Deployments/Governance Sweep); §4 API Endpoint Definitions (4-column table); §5 Error Codes (2-column table).

## Verification counts

- **Endpoints: 50 / 50 present** (0 missing; every scaffold path string found verbatim in the §4 table).
- **Error codes: 39 / 39 present** (0 missing; §5 table has exactly 39 rows).
- **Enum values: 0 missing.** **State-machine states: 0 missing** across all 10 machines (58 transitions walked).
- **§2.2 byte-verbatim from `section-2.2-response-structure.md`: confirmed.**
- **Fuzzy-word scan ("approximately", "roughly", "conservatively", "should be", "maybe"): 0 hits.**
- **Last line of file:** `| \`ERR_PORTFOLIO_REACH_CAP_EXCEEDED\` | 422 |` — a completed table row at a real section boundary.

## Hard Contract reports

**CONTRACT 1 — FIELD-NAME COVERAGE: PASS.** 147 required identifiers extracted mechanically from the scaffold (all entity field names across the 12 entities, plus every endpoint `input` key and every endpoint `output` key, recursively). All 147 appear verbatim inside backticks in PRD.md. Missing: 0. Two independent extraction passes (flat, then recursive-walk) both returned 0 missing.

**CONTRACT 2 — RULE COVERAGE: PASS.** All 41 validations are enumerated 1–41 in §2.9 in priority order, each with its error ID, HTTP status and full `applies_to` scope — including the priority-23 asymmetry (approval consults the tier's `REQUIRED_EVALS`; `SECURITY` gate clearance consults only `SECURITY_REDTEAM`), the priority-40 inclusive-comparison rationale, and the priority-41 HIGH-tier-only cap. All 58 state-machine transitions across 10 entities are narrated in §3 with their triggers and side effects. All 11 calculations are rendered in prose with every constant (risk classification, vendor terms grading with both variants, oversight adequacy incl. the 2-D `REQUIRED_ADEQUACY` table, per-gate control debt, six-step approval finalization, frozen eval threshold profile, both window-conflict semantics — half-open for evaluations, closed-plus-7-day-buffer for notices, incident containment deadline, posture derivation, shadow grace deadline, conserved quantities). Both OCC rules appear in §2.6; all cross-entity cascades (asset revision, approve-for-use, binding supersession, use-case revocation's four hops, incident suspension/reinstatement, sweep step 3's three hops) appear with their hop ordering. Sibling branches are written at equal density (classify ordinary/prohibited; vendor decide ACCEPT/REJECT; oversight decide APPROVE/REJECT; eval PASSED/FAILED; contain CONTAINED/ESCALATED; reassessment CONFIRMED/SUSPEND; the three shadow dispositions). All 12 ledger `entry_type` values and both conserved quantities are specified.

**CONTRACT 3 — §3 PATH PURITY: PASS.** Every backticked token in §3 was scanned: 0 tokens start with `/`, 0 are a bare HTTP method, and 0 combine method+path. Operations in §3 are named by state-transition framing, role+action verb, or capability description; the endpoint-scoped validation ladder deliberately lives in §2.9 instead.

Both withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

**Orchestrator anti-truncation check (independent):** `wc -l` = 479, `wc -c` = 106457, 28 `^#` headings, 39 `^| \`ERR_` rows; tail ends with the complete final table row `| \`ERR_PORTFOLIO_REACH_CAP_EXCEEDED\` | 422 |`. Not truncated — no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T03:47:00.000Z

All seven writers reported and the suite is complete and self-audited clean.

## Files written

**Stage 1 — `test_helpers/`** (9 files)
`__init__.py` (barrel, 329 public names), `constants.py`, `api_errors.py`, `types.py`, `test_users.py`, `api_client.py` (one method per each of the 50 endpoints), `factories.py`, `assertions.py`, `fixtures.py` (24 named governance chains).

**Stage 2 — `test_suite/`** (`conftest.py` + 7 test modules)

| file | tagged tests |
|---|---|
| `test_difficulty_calculations_and_state.py` | 28 |
| `test_difficulty_cascades_and_boundaries.py` | 21 |
| `test_difficulty_dependencies_and_invariants.py` | 19 |
| `test_corner_errors.py` | 20 |
| `test_corner_entities_and_state_machines.py` | 18 |
| `test_corner_calculations_validations_endpoints.py` | 18 |
| `test_corner_rbac_and_layers.py` | 15 |

## Counts per source queue

- **Queue A (Difficulty, §1.8): 68 tests** across all 18 depth instances — every instance has ≥2 tests (target met, 0 gaps).
- **Queue B (Corner, §1.9): 71 tests** across 67 of 69 live breadth instances.
- **139 tagged test functions → 142 collected pytest items** (3 extra from two genuine `parametrize` families in the disclosure-window instance).
- **18 breadth stubs**: all 18 `excluded_because:` cross-references independently verified to resolve to real `(rule_id, instance_name)` pairs in the difficulty index; **nothing emitted for any of them**.

## Instances skipped (2, both queue B `entities`)

Both fail the two-condition filter on **unique derivability**, not coverage. The PRD never uses the word "ignored" and §2.9 item 8's enumeration of shape violations says nothing about unknown or non-updatable body keys, so 201/200-and-silently-drop and 400-`ERR_INVALID_REQUEST` are equally PRD-consistent:

1. `use_case_requester_user_id_is_system_assigned_extra_field_ignored` — asserts a supplied `requester_user_id` is silently ignored with 201.
2. `use_case_business_unit_not_editable_input_ignored` — asserts a PATCH carrying `business_unit` returns 200 and leaves the field unchanged. (§3.2 *does* say it "may not be changed after filing", but the HTTP outcome of trying is undetermined.)

No weakening, no placeholders, and **no `skip`/`skipif`/`xfail` markers anywhere in the suite**.

## Stage-2 self-audit (`/tmp/audit_2494.py`, AST-driven)

`ERRORS: 0`. Verified mechanically across all 7 files: exactly one `Design:` line per test and always the docstring's last line; every tag matches the required grammar and resolves to a live registry entry; **zero tags pointing at stubs or non-existent instances**; every quoted run ≥25 chars in every docstring matches `workspace/PRD.md` whitespace-normalized (0 misses out of ~350 citations); no skip/xfail constructs; zero case-insensitive occurrences of "scaffold". Also: `pytest --collect-only` → 142 collected, 0 errors, 0 warnings; `pyflakes` clean across `test_helpers/` and `test_suite/` (barrel re-exports excluded).

## Four Stage-1 defects found by cross-agent review and fixed

Multiple writers independently flagged these; I verified each against the PRD and repaired `test_helpers/`, then threaded the signature changes through the ~17 affected call sites:

1. `assertions.assert_use_case` asserted `active_binding_count`, which PRD §2.10 declares on `ModelAsset` only — it would have `KeyError`d on 40+ call sites against a correct implementation. Removed.
2. `factories.test_evaluation_payload` omitted `use_case_id`, which PRD §3.4 declares as scheduling input. Renamed to `evaluation_schedule_payload` with `use_case_id` threaded through `schedule_evaluation`/`run_evaluation`; the old name is kept as an alias carrying `__test__ = False` so pytest can't collect the factory itself as a test.
3. `factories.evaluation_completion_payload` posted `observed_metric_value`, but PRD §3.4 says the body "must contain whichever of the three `required_metric_name` designates" and that `observed_metric_value` is where the server *stores* it — a body posting it would be rejected `ERR_INVALID_REQUEST`. Now keys the metric by `eval_type`/`metric_name`, with `complete_evaluation` reading `required_metric_name` off the scheduled row when the type isn't passed.
4. `factories.shadow_link_payload` sent `claimed_use_case_id`; PRD §3.9 says the officer supplies `use_case_id` and `claimed_use_case_id` is the field the record sets from it. Fixed.

Without fixes 2 and 3 every evaluation-bearing chain (`limited_approved_use_case`, all `high_tier_*`) would have failed in setup against a PRD-conformant server.

Nothing under `workspace/implementation/` was read or written at any point.

## Step 6: Generate implementation — 2026-09-03T03:47:00.000Z

Implementation complete and verified live. Both end-to-end smoke suites pass (`FAILURES: 0`) against a freshly booted server, and the two scratch servers I used were shut down by port.

## Files written

All under `workspace/implementation/`:

| File | Lines |
|---|---|
| `start.sh` | 10 |
| `requirements.txt` | 1 |
| `app.py` | 109 |
| `clock.py` | 42 |
| `constants.py` | 266 |
| `db.py` | 82 |
| `errors.py` | 107 |
| `middleware.py` | 49 |
| `response.py` | 92 |
| `validators.py` | 206 |
| `services/__init__.py` | 0 |
| `services/calc.py` | 285 |
| `services/cascades.py` | 246 |
| `services/guards.py` | 107 |
| `services/queries.py` | 106 |
| `routes/__init__.py` | 0 |
| `routes/model_assets.py` | 247 |
| `routes/use_cases.py` | 710 |
| `routes/review_gates.py` | 242 |
| `routes/oversight.py` | 63 |
| `routes/evaluations.py` | 161 |
| `routes/notices.py` | 39 |
| `routes/incidents.py` | 178 |
| `routes/shadows.py` | 169 |
| `routes/ops.py` | 166 |
| **total** | **3683** |

No SQLite, no JSON on disk, no `/tmp` cache: all 12 collections are plain dicts in `db.py`, empty at boot. The logical clock starts at `2026-08-01T00:00:00Z` on every fresh process and only `POST /_clock/set_current_utc` moves it. `start.sh` does a guarded `pip install` (skipped when Flask already imports, to avoid boot contention under 8 concurrent per-test reboots) and then `exec python3 app.py`, binding `0.0.0.0:${PORT:-10000}`.

## Endpoints

All 50 declared routes are registered (confirmed by dumping `app.url_map`): model assets 1-9 (`/model-assets` CRUD + `approve-for-use` + `vendor-assessments` + `/vendor-assessments/{id}/decide` + nested bindings list), use cases 10-16 and 21-24 and 30-36 (intake, PATCH, classify, bindings, approve, revoke, complete-reassessment, classification-snapshots, ledger-entries, disclosure-notices, oversight-designs, review-gates list), review gates 17-20 (`start-review`, `issue-conditions`, `clear`, `reopen`), oversight 25 (`/oversight-designs/{id}/decide`), evaluations 26-29, notices 32 + withdraw, incidents 37-41, shadow deployments 42-47, and ops 48-50 (`GET /inventory-summary`, `POST /_clock/set_current_utc`, `POST /_ops/governance-sweep`).

## Verified behaviour highlights

Envelope/meta shape with exactly 3 fractional digits and `req_` + 20 alnum ids; pagination bounds (`limit` 0/101, `offset` -1 → 400); the full ladder order (401 role → 403 → path 404 → body FK 404 left-to-right → body shape 400 → 412 OCC → 409 state); exact-rational debt (`1.35 / 0.63 / 0.58 / 0.38` summing to the mandated **2.94** — round-per-gate-then-sum, since sum-then-round yields 2.93); approval finalization (`control_credit` capped at 15, final 67 → LIMITED, 365-day interval, expiry == reassessment due); vendor grading under both variants; oversight adequacy thresholds; evaluation half-open window exclusivity vs the notice closed-interval + 7-day quiet buffer; SEV1 → IMPAIRED → SUSPENDED with `APPROVAL_SUSPENDED` ledger; 4-hop revoke and sweep cascades; sweep asymmetry (`>=` for reassessment, `>` for expiry and grace); reach/debt conservation returning to 0 after revoke.

## PRD vs SCAFFOLD disagreements (PRD favoured unless noted)

1. **UseCase.version bumps** — the sharpest conflict. PRD §2.10 says every mutated row bumps its version; SCAFFOLD enumerates version increments per transition and omits them for gate-driven bubble-ups (issue-conditions, start-review, clear, reopen, failed evaluations). I followed **SCAFFOLD** here, because the four OCC endpoints need a predictable version sequence (create v1 → classify v2 → binding v3 → oversight design v4 → approve); PRD's reading would make `expected_use_case_version` unguessable from the client side. This is the one place I deliberately preferred SCAFFOLD, and it is the highest-risk divergence if the test suite reads PRD §2.10 literally.
2. **Clear-gate check ordering** — §2.9's normative ladder (steps 23 → 26 → 27) contradicts §3.3's prose ordering; the ladder wins.
3. **Reopen and `open_condition_count`** — PRD §3.3 says reopen resets it to 0; SCAFFOLD says "restored to the value implied by `debt_before_clear`". PRD followed.
4. **Asset RESTRICTED cascade** — SCAFFOLD triggers it only on revoke hop 3 and sweep step 3; PRD prose reads as a fact-based invariant on `active_binding_count → 0`. Implemented as trigger-based per SCAFFOLD's explicit trigger list.
5. **Shadow `link` source states** — PRD prose says "from either DISCOVERED or GRACE_GRANTED", but ladder step 18 declares only RETIRED and ENFORCED_BLOCK as blocking, so linking from LINKED is permitted. Ladder followed; minor ambiguity.
6. **`ERR_MODEL_ASSET_NOT_APPROVED_FOR_USE` carries two statuses** — 409 on asset approve-for-use/PATCH, 422 on binding creation. Both are attested in different places; implemented per-endpoint.
7. **Derived counters** (`open_conditions_count`, `cleared_gate_count`, `active_binding_count`, `enforced_shadow_count`, `vendor_terms_grade`, `monitoring_posture`) recompute in place without a version bump.
8. **PRIVACY gate vs approval notice strictness** — gate clearance needs only a PUBLISHED notice per jurisdiction; approval additionally requires one in force at `now`.
9. **Undeclared error ids** (no id given by either doc; chose the nearest declared one): ownership violations → `ERR_UNAUTHORIZED` 403; PATCH from a non-DRAFT/CHANGES_REQUESTED status → `ERR_USE_CASE_NOT_IN_DRAFT`; revoke from an ineligible status → `ERR_USE_CASE_NOT_READY_FOR_APPROVAL`; CONFIRMED reassessment with a non-HEALTHY posture → `ERR_REASSESSMENT_NOT_DUE`; non-officer containing an ESCALATED incident → `ERR_UNAUTHORIZED`; gate action while the parent use case is in the wrong status → `ERR_GATE_NOT_IN_REVIEWABLE_STATE`.
10. **Null-tier fallbacks** (unspecified in both): evaluation profile → MINIMAL, containment speed factor → LIMITED, reassessment interval for a PROHIBITED/null final tier → 180 days.
11. **`GET /inventory-summary` filtered semantics** — neither doc states whether filters scope the ledger/gate/incident/shadow aggregates. I scope every quantity to the filtered use-case id set so both conservation invariants (`portfolio_approved_reach == ledger_reach_balance`, debt total vs ledger debt) hold on a slice as well as on the whole portfolio.

Two real defects were found and fixed during verification: `routes/ops.py` passed the dict rather than its values to the ordering helper (500 on `GET /inventory-summary` and in the sweep), and `app.py`'s request lock could be released cross-thread (now gated on a per-request `g._holds_lock` flag). `pyflakes` is clean (rc=0).

**Orchestrator note carried into Step 7:** the impl generator's disagreement #1 is a deliberate departure from the PRD-First contract — it followed SCAFFOLD over PRD §2.10 on `UseCase.version` bump semantics. Implementers may not read SCAFFOLD, so if any Step 7 failure traces to this, the resolution is governed by PRD §2.10's verbatim text under the normal STEP 1a/1b/2/3 protocol, with SCAFFOLD carrying no authority. This was flagged explicitly to the Step 7 subagent.

## Step 7: Run tests and iterate — 2026-09-03T04:20:00.000Z

# Summary

## Iterations run
**1 full 8-round parallel sweep** (all 8 rounds green on the first sweep after the fix batch). Diagnosis was done beforehand with a two-stage fast probe harness (whole-suite single-server scan to enumerate candidates, then a fresh-server-per-node re-run to separate genuine failures from single-server shared-state artifacts), which cut a ~40-minute sweep round down to seconds per iteration. 27 → 20 probe candidates, of which all 20 proved to be shared-state artifacts of the probe and 0 genuine.

## Tests deleted
**None.** No failure traced to PRD silence at the whole-test level; the one silence found was partial (STEP 1c) and was handled by dropping a single assertion kwarg.

## Fixes applied to `test_helpers/`
- `test_helpers/assertions.py` — added `parse_instant()`; rewrote `assert_iso_instant` to compare the *parsed* instant after checking well-formedness. PRD §2.4 renders stamps with three fractional digits and §2.5 says comparisons are "exact to the second in UTC", so `...T06:00:00Z` and `...T06:00:00.000Z` are the same instant; the old raw-string compare tested a rendering the PRD does not pin.
- `test_helpers/assertions.py` — `_assert_expected()` now detects instant-shaped expectations (`_INSTANT_RE` / `_looks_like_instant`) and compares them as instants, for the same reason.
- `test_helpers/factories.py` — `parse_ts()` replaced strict `strptime("%Y-%m-%dT%H:%M:%SZ")` with `fromisoformat`-based parsing, so values read back off a record (which carry `.000`) can be fed to `plus_days` / `plus_hours` / `plus_seconds`.
- `test_helpers/fixtures.py` — `revoke_use_case()` now sends `revocation_payload()` instead of an empty body (imported `revocation_payload`). PRD §3.8: revocation "takes a free-text `revocation_reason`", so the empty body was correctly refused with `ERR_INVALID_REQUEST`.

## Fixes applied to `test_suite/`
- `test_difficulty_dependencies_and_invariants.py` — three bare `== "20xx-...Z"` timestamp comparisons (`window_start_at`, `window_end_at`, notice `effective_to`) converted to `assert_iso_instant(...)`; same rendering-vs-instant issue.
- `test_difficulty_dependencies_and_invariants.py::TestSecurityGateClearDependsOnEvaluationRowStatus::test_clear_is_refused_while_no_redteam_evaluation_exists` — the "refused clear wrote nothing" version check was anchored on `chain.gates["SECURITY"]` (version 1, captured *before* the take-up bumped it to 2). Now anchored on the row returned by `take_up_gate`, i.e. the state immediately before the refused clear. Assertion strength unchanged.
- `test_difficulty_cascades_and_boundaries.py:648` — dropped only the `pinned_risk_tier="HIGH"` kwarg from `assert_test_evaluation(scheduled, ...)`. **STEP 1c partial coverage:** PRD §3.4 names only `required_metric_name`, `required_metric_threshold`, `required_sample_size` on a frozen evaluation profile; `pinned_risk_tier` is a `ReviewGate` field (§3.2/§3.3) and is never stated as a `TestEvaluation` attribute. All other assertions in the call kept.
- `test_corner_entities_and_state_machines.py::TestUseCaseLifecycle::test_reclassification_voids_the_previous_cycle_and_opens_a_new_set` — the test PATCHed intake while the use case was `UNDER_REVIEW`, which PRD §3.2 forbids ("only from `DRAFT` or from `CHANGES_REQUESTED`"); the implementation was correct to answer 409. Setup now drives the use case to `CHANGES_REQUESTED` first by taking up the PRIVACY gate and issuing conditions (PRD §3.3: "the use case bubbles `UNDER_REVIEW → CHANGES_REQUESTED`"). Every downstream assertion — voided cycle-1 gates at index 1 with debt 0.00, 2 fresh PENDING gates at index 2, `risk_score == 51`, snapshot `risk_score [49, 51]` and `reach_points [2, 4]` — was preserved unchanged and passes.

## Fixes applied to `implementation/`
**None.** No confirmed failure survived STEP 1/STEP 2 as an implementation defect. In particular the flagged PRD §2.10 `UseCase.version`-bump divergence (gate-driven bubble-ups in `routes/review_gates.py` not calling `db.touch(use_case)`) never produced a failure, because the fixtures read the current version back via `current_version()` rather than predicting it — so no test pins the bumped value. It remains a latent divergence from §2.10's "every affected row is mutated in the same request", but under the cardinal rules there was no failing test to justify touching the implementation.

## Final sweep evidence (fresh read, 8/8 files present, `passed == total`)
| file | passed / total |
|---|---|
| `workspace/implementation/results.1.json` | 142 / 142 |
| `.../results.2.json` | 142 / 142 |
| `.../results.3.json` | 142 / 142 |
| `.../results.4.json` | 142 / 142 |
| `.../results.5.json` | 142 / 142 |
| `.../results.6.json` | 142 / 142 |
| `.../results.7.json` | 142 / 142 |
| `.../results.8.json` | 142 / 142 |

Sweep ran under `setsid nohup` (pgid 305771), all 8 rounds concurrent, joined with `wait`, no early exit; process group confirmed gone before reading. Sweep log: `workspace/sweep.log`. Diagnostic scratch scripts (`probe.sh`, `probe_isolated.sh`) were removed from `workspace/`.

**Orchestrator independent verification of Step 7 evidence:** all 8 `results.*.json` exist (mtime 04:03, consistent with one concurrent sweep), each parses to `passed=142 / total=142 / failed=0`; `grep` for `pytest.mark.skip` / `pytest.mark.xfail` across `test_suite/` and `test_helpers/` returns zero hits. Step 7's clean-sweep claim is confirmed, not taken on trust.

**Step 8 skip condition evaluated (see Step 8 entry below):** NOT skipped. Step 7 applied 4 `test_helpers/` fixes and 4 `test_suite/` fixes (0 deletions, 0 `implementation/` fixes), so the pipeline did iterate beyond baseline and Step 8 runs on that diff. Note for Step 8/9: because `implementation/` fix count is 0, most `<step_7_diff>` items are pure test-artifact bugs that imply no PRD edit; Step 8 is expected to be a very small or empty diff, and the substantive PRD alignment work (including the latent §2.10 `UseCase.version` divergence, which no test pinned) falls to Step 9's full impl scan.

## Step 8: Finalize PRD — 2026-09-03T04:35:00.000Z

PRD_FINALIZED.md is complete and verified. Final report:

## Deliverable

`workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md = 479 → PRD_FINALIZED.md = 484. Delta **+5 lines (+1.04%)**. Diff confirms exactly 7 changed hunks and no other content change anywhere in the document.

## Changes

- **§2.4 — insert — instant rendering is uniform across the whole API (every instant-valued response field, including client-supplied instants and the clock echo, is emitted UTC with exactly three fractional digits + `Z`, finer input truncated to whole ms; comparisons are on the instant, not the rendering)** — `implementation/clock.py:29-34`, `implementation/response.py:29-40`, `implementation/routes/ops.py:83`
- **§2.4 — revise — the "every mutation bumps `version`" sentence now defers to the two narrower disciplines §2.10 sets out for `UseCase` and `ModelAsset`** — `implementation/db.py:62-66`
- **§2.9 step 11 — revise — `ERR_USE_CASE_NOT_IN_DRAFT` (409) also answers an intake revision attempted from a status that is neither `DRAFT` nor `CHANGES_REQUESTED`** — `implementation/routes/use_cases.py:179-183`, `implementation/errors.py:62`
- **§2.10 — revise — version-bump scope narrowed: counter recomputation and child-driven parent status bubble-ups do not touch the row; `UseCase` bumps only on the operations addressed to it plus the suspend/reinstate cascades; `ModelAsset` bumps on revision, clearance, `RESTRICTED` and the sweep's `enforced_shadow_count` increment but not on `active_binding_count`/`vendor_terms_grade` changes; "every other **versioned** record kind" bumps on any field change** — `implementation/routes/review_gates.py:70-72,97-101,183-200,230-241`, `implementation/routes/evaluations.py:156-160`, `implementation/services/cascades.py:35-41,104,119,145,158,189,246`, `implementation/routes/ops.py:107,149-156`, `implementation/routes/use_cases.py:205,249,328,329,391,607,689`
- **§3.2 — insert — a revision from a non-editable status is `ERR_USE_CASE_NOT_IN_DRAFT` (409), but a `REJECTED`/`REVOKED` use case answers `ERR_USE_CASE_TERMINAL` at step 10 first** — `implementation/routes/use_cases.py:178-183`
- **§3.4 — insert — the frozen evaluation profile is exactly `required_metric_name`, `required_metric_threshold`, `required_sample_size`; a `TestEvaluation` carries no `pinned_risk_tier` or any tier field (`pinned_risk_tier` belongs to a `ReviewGate`)** — `implementation/routes/evaluations.py:56-75`, `implementation/services/calc.py:235-245`
- **§3.8 — insert — `revocation_reason` is a mandatory string with no length bound and no default; omitted/null/non-string is `ERR_INVALID_REQUEST` (400) at step 8** — `implementation/routes/use_cases.py:623-625`, `implementation/validators.py:29-41`

## Pre-edit search log (NO-NEW-MISMATCH)

1. **Subject: instant rendering vs instant comparison.** Enumerated: `clock.py` (`iso`, `now`, `set_now`, `plus_days`), `response.py` (`serialize_value`, `object_response`, `list_response`, `_meta`), `validators.py` (`parse_datetime`, `as_datetime`), plus grep for `strftime|isoformat|iso(` across `implementation/`. Confirmed `clock.iso` is the *only* renderer and `response.serialize_value` funnels every `datetime` through it, so the claim is safely universal — including `ops.py:83`'s `current_utc` echo and client-supplied `window_*`/`grace_deadline_at` values. Wording adjustment: added "with a finer-grained input truncated to whole milliseconds" because `iso` floors `microsecond // 1000` rather than rounding; and scoped the claim to *rendering* so it makes no promise about sub-ms comparison behaviour (which `parse_datetime` preserves).

2. **Subject: `db.touch` inventory / version-bump scope.** Enumerated by grepping `db.touch|version.*+ 1|_count\]` across all of `implementation/`: `db.py:62`, `routes/use_cases.py` (7 sites), `routes/model_assets.py:97,131,246`, `routes/review_gates.py` (4 gate actions), `routes/evaluations.py`, `routes/bindings.py`, `routes/vendor_assessments.py`, `routes/oversight.py`, `routes/disclosures.py`, `routes/incidents.py`, `routes/shadows.py`, `routes/ops.py`, `services/cascades.py` (all 9 cascade functions). Adjustments: **(a)** dropped a drafted general rule "recomputing a derived counter never bumps the row's version" — false, because `ops.py:148-156` increments `enforced_shadow_count` and then *always* bumps the asset (via `restrict_asset`'s touch or the explicit `db.touch(asset)`); replaced with a per-record-kind enumeration. **(b)** changed "Every other record kind" to "Every other **versioned** record kind" so `ClassificationSnapshot`/`GovernanceLedgerEntry`, which have no `version` at all, are not falsely included. **(c)** added the "reads it back off the use case rather than predicting it" clause because §2.6's four pinned operations are the only client-visible consequence. Cross-checked all 15 pre-existing "the use case's `version` increments" sentences in the PRD (§3.2, §3.3, §3.4, §3.5, §3.7, §3.8, §3.9) — every one names an operation my new bullet also bumps, and the PRD nowhere claims a gate action or evaluation outcome bumps the use case, so no pre-existing sentence had to be revised.

3. **Subject: `ERR_USE_CASE_NOT_IN_DRAFT` on intake revision.** Enumerated: `routes/use_cases.py` PATCH handler (guard order 178→183), `services/guards.py` (`check_not_terminal`, `check_owner`, `check_in_draft`), `errors.py:62` for the status code, grep for `NOT_IN_DRAFT` across `implementation/` (three raise sites: PATCH revision, classification, and none other). Adjustment: my first draft said "any other status", which is wrong for `REJECTED`/`REVOKED` since `check_not_terminal` fires first; added the explicit step-10-before-step-11 qualification, and mirrored it into the §2.9 step 11 revision rather than inventing a new ladder step.

4. **Subject: frozen evaluation profile field set.** Enumerated: `routes/evaluations.py:56-75` (the record literal), `services/calc.py:225-250` (`evaluation_profile` returns a 3-tuple), grep for `pinned_risk_tier` across `implementation/` (only `routes/review_gates.py` gate creation) and `pinned_` generally. Adjustment: added the parenthetical pointing `pinned_risk_tier` at `ReviewGate` so the negative claim cannot be misread as "no record has this field". Deliberately did **not** document `calc.py:241`'s `MINIMAL` fallback for an unclassified tier — no step_7_diff item touches it.

5. **Subject: `revocation_reason` requiredness.** Enumerated: `routes/use_cases.py:600-700` (revoke handler; `as_str(body, "revocation_reason", required=True)` at 624), `validators.py:29-41` (`as_str` → `bad_request`), `errors.py` (`bad_request` → `ERR_INVALID_REQUEST`/400), `services/cascades.py:200-260` (`revoke_use_case`, which also writes the literal `"SUPERSEDED"` reason on a predecessor at `use_cases.py:613` — a *different* field, left undocumented as out of scope), plus grep for `revocation_reason` across `implementation/` (init to null at intake, the revoke write, and the successor cascade). No wording adjustment needed beyond pinning the ladder step to 8.

Remaining step_7_diff items — the `factories.parse_ts`/`fromisoformat` fix, the four `test_suite` timestamp-comparison fixes, the gate-version anchoring fix, and the reclassification test's `CHANGES_REQUESTED` setup fix — are all downstream of silences 1, 2 and 3 above, or are pure test-artifact bugs, and implied no further PRD edit. `implementation/` was not modified.

**Orchestrator verification:** `PRD_FINALIZED.md` exists, 484 lines vs PRD.md's 479, `diff` reports 19 changed lines across 7 hunks — a real, non-empty, appropriately minimal patch.

**Step 9 execution plan (orchestrator decision).** Step 9 is run as THREE sequential file-partitioned passes over the same `PRD_COMPLETED.md`, rather than one subagent asked to scan all 3682 implementation lines at once. Rationale: a single-pass Step 9 on an implementation this size has previously returned a `PRD_COMPLETED.md` byte-identical to its input — i.e. the scan silently did not happen — and partitioning by implementation file makes each pass's exhaustiveness obligation small enough to actually discharge. The passes must be sequential, not concurrent, because all three edit the same output file. Partition (3682 lines total):
- **Pass A — infrastructure & shared machinery (1054 lines):** `app.py`, `clock.py`, `constants.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `validators.py`, `services/guards.py`, `services/queries.py`.
- **Pass B — domain core (1241 lines):** `services/calc.py`, `services/cascades.py`, `routes/use_cases.py`.
- **Pass C — remaining route surface (1265 lines):** `routes/model_assets.py`, `routes/review_gates.py`, `routes/oversight.py`, `routes/evaluations.py`, `routes/notices.py`, `routes/incidents.py`, `routes/shadows.py`, `routes/ops.py`.
The orchestrator performs the `cp PRD_FINALIZED.md PRD_COMPLETED.md` itself before Pass A so no pass can clobber an earlier pass's edits.

## Step 9: Complete PRD — 2026-09-03T04:47:00.000Z

Run as three sequential file-partitioned passes over a single `PRD_COMPLETED.md` (seeded by the orchestrator with `cp PRD_FINALIZED.md PRD_COMPLETED.md` before Pass A, so no pass could clobber an earlier one). Each pass edited in place with the Edit tool only; every pass independently confirmed the prior passes' hunks were still present.

### Pass A — infrastructure & shared machinery (`app.py`, `clock.py`, `constants.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `validators.py`, `services/guards.py`, `services/queries.py`)

Buckets: already-pinned ~74 / ambiguity-pinned 13 / mismatch-revised 0. 484 → 485 lines.

- §2 (preamble) — insert — ambiguity — trailing slash equivalent to its absence — `app.py:33`
- §2.1 — revise — ambiguity — whitespace-only header counts as blank; role matched exactly/case-sensitively — `middleware.py:13-18`
- §2.1 — insert — ambiguity — `X-User-ID` recorded and compared verbatim (no trim, no case fold) — `middleware.py:19`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from `A`–`Z`/`0`–`9` — `response.py:12,16`
- §2.2 — revise — ambiguity — `api_request_timestamp` comes from the logical clock, not the host wall clock — `response.py:22-23`
- §2.2 — insert — ambiguity — envelope for non-4xx/off-table failures: unknown route → `ERR_GOVERNANCE_RECORD_NOT_FOUND` 404, bad method → `ERR_INVALID_REQUEST` 405, unexpected exception → `ERR_INVALID_REQUEST` 500 with `internal server error:` message — `app.py:67-94`
- §2.3 — revise — ambiguity — `offset` unbounded above / past-end page still reports full `total_count`; non-integer `limit`/`offset` → 400; empty value takes the default — `validators.py:170-182`, `response.py:74-82`
- §2.3 — revise — ambiguity — `created_at` ties broken by server creation sequence, so ordering is total and stable — `db.py:69-71`
- §2.3 — revise — ambiguity — filters matched by exact equality without enum validation (unknown value → empty page, not 400); empty filter value ignored; `is_third_party` accepts `true/false/1/0` any case, else 400 — `validators.py:185-201`
- §2.4 — insert — ambiguity — input instants: `Z`/numeric offset normalised to UTC, offset-less instant read as UTC rather than rejected — `validators.py:131-143`
- §2.7 — insert — ambiguity — two-decimal debt figures (`control_debt_index`, `debt_delta`, portfolio total) serialised as JSON numbers, not strings — `response.py:33-34`
- §2.9 step 7 / step 8 — revise — ambiguity — only a present string FK is resolved at step 7; absent/`null`/other-typed keys fall through to step 8; plus the universal body conventions (absent/empty body = `{}`, non-object/invalid JSON → `ERR_INVALID_REQUEST`, explicit `null` = omission) and the presence-not-value semantics of the "no updatable field" test — `guards.py:49-63`, `validators.py:12-27,204-206`
- §3.2 — insert — ambiguity — a revision body naming an updatable field as explicit `null` still runs the full revision cascade while changing no intake field — `validators.py:204-206`, `routes/use_cases.py:168`

Pass A confirmed all five Step 8 pins hold against its files, and handed one open question to Pass B: `constants.REASSESSMENT_INTERVAL_DAYS` has no `PROHIBITED` key while §3.7 step 4 says the prohibited override still applies to `final_risk_tier` — potential 500.

### Pass B — domain core (`services/calc.py`, `services/cascades.py`, `routes/use_cases.py`)

Buckets: already-pinned ~60 (plus 5 candidate findings screened out as unreachable and deliberately left unpinned: `vendor_penalty_for_asset`'s null-grade default, `gate_control_debt`'s defensive guards, `classification_stale` at approval, `complete_reassessment`'s interval fallback, and `portfolio_control_debt` as dead code) / ambiguity-pinned 13 / mismatch-revised 4. 485 → 485 lines (all edits in-paragraph).

- §3.1 (RESTRICTED paragraph) — revise — mismatch — the `active_binding_count`-reaches-0 restriction trigger is scoped to the revocation cascade; a binding merely superseded by a newer binding decrements the count without restricting the asset — `routes/use_cases.py:313-315` vs `services/cascades.py:224-230`
- §2.10 (`vendor_terms_grade` bullet) — revise — mismatch — the grade tracks the last **filed** `ACCEPTED` assessment in `created_at`/creation-sequence order, not the most recently *decided* one — `services/cascades.py:116-119`
- §3.1 (assessment decide) — revise — mismatch — accepting *re-derives* the asset grade by that rule (can land on a later-filed, earlier-accepted row); rejecting leaves it where it stood because the accepted set is unchanged — `services/cascades.py:116-119`, `routes/model_assets.py:244-246`
- §3.5 (threshold paragraph) — revise — mismatch — PRD claimed a design "cannot be decided" with a null tier; in fact `required_adequacy_score` is stored null and only **approval** is refused (`ERR_OVERSIGHT_DESIGN_INADEQUATE`), rejection still succeeds — `services/calc.py:207-213`, `routes/use_cases.py:382-384`
- §3.7 step 5 — insert — ambiguity — a `PROHIBITED` deployment-final tier (and any tier the table does not name) takes the 180-day fallback interval — `services/calc.py:284-285`
- §3.2 (prohibited branch) — insert — ambiguity — the gate-voiding sweep runs on the prohibited branch too, before the "no gates created" outcome — `routes/use_cases.py:230`, `services/cascades.py:70-79`
- §3.2 (ordinary branch) — insert — ambiguity — fresh-gate field set: `version` 1, empty `conditions`, counters 0/0.00, `debt_before_clear` 0.00, four nulls — `services/cascades.py:48-64`
- §3.3 (voiding paragraph) — insert — ambiguity — voiding rewrites nothing else: `conditions`, `debt_before_clear`, `assigned_reviewer_user_id`, `cleared_by_user_id`, `cleared_at`, `decision_note` all survive — `services/cascades.py:70-79`
- §3.2 (revision paragraph) — insert — ambiguity — a non-owning `Requester` gets `ERR_UNAUTHORIZED` (403) as soon as `{id}` resolves, before body parsing and before the terminal check — `routes/use_cases.py:161-166`
- §3.2 (revision paragraph) — insert — ambiguity — `risk_score`, `risk_tier` and `required_gate_types` survive a revision uncleared; `classification_stale` is the only signal — `routes/use_cases.py:202-205`
- §3.4 (profile freeze) — insert — ambiguity — scheduling against an unclassified use case is allowed and freezes the `MINIMAL` profile — `services/calc.py:235-245`
- §3.8 (containment clock) — insert — ambiguity — both tiers null ⇒ `LIMITED`'s 1.0 speed factor — `services/calc.py:260-264`
- §3.8 (revocation availability) — insert — ambiguity — a disallowed non-terminal status answers `ERR_USE_CASE_NOT_READY_FOR_APPROVAL` (409) — `routes/use_cases.py:626-636`
- §3.8 hop 4 — insert — ambiguity — **one** `VENDOR_ASSESSMENT_EXPIRED` entry per expired assessment — `services/cascades.py:122-137`
- §3.8 (cascade close-out) — insert — ambiguity — bindings walked in `created_at` order, notices withdrawn after all four hops; exact ledger order `APPROVAL_REVOKED` → `BINDING_RETIRED`* → `VENDOR_ASSESSMENT_EXPIRED`* → `DISCLOSURE_WITHDRAWN`* — `services/cascades.py:193-246`
- §3.9 (CONFIRMED bullet) — insert — ambiguity — a `WATCH`/`IMPAIRED` posture answers `ERR_REASSESSMENT_NOT_DUE` (409), tested after SoD and after `ERR_APPROVAL_EXPIRED`, only on this outcome — `routes/use_cases.py:667-671`
- §3.9 step 3 hop 3 — insert — ambiguity — the sweep's expiries also append one `VENDOR_ASSESSMENT_EXPIRED` each, actor `system`, against `claimed_use_case_id`, and none when it is null — `services/cascades.py:122-137`, `routes/ops.py:149-151`

**Pass A's `PROHIBITED` question — resolved, no 500 risk.** `calc.reassessment_interval_days` (`services/calc.py:284-285`) is `constants.REASSESSMENT_INTERVAL_DAYS.get(final_risk_tier, 180)` — a `.get` with a 180 default, so the missing `PROHIBITED` key cannot raise. The case is **reachable**, but not via the four-condition override (that always rejects at classification into terminal `REJECTED`, and a revision that would introduce it forces `DRAFT` + `classification_stale`, both of which block approval). It is reachable through the bands: provisional `HIGH` with `base_score` ≤ 84 (so step 21 lets it through), four cleared gates plus three passed evals capping `control_credit` at 15, and a grade-`D` third-party asset contributing `vendor_penalty` 25 ⇒ `84 + 25 − 15 = 94 ≥ 85` ⇒ `final_risk_tier` `PROHIBITED`, interval 180 days, step 41's HIGH reach cap skipped. Grade `D` on an `APPROVED_FOR_USE` asset is reachable because clearance only requires *some* accepted A/B/C assessment while `vendor_terms_grade` follows the latest-filed accepted row. Pinned in §3.7 step 5.

### Pass C — remaining route surface (`routes/model_assets.py`, `review_gates.py`, `oversight.py`, `evaluations.py`, `notices.py`, `incidents.py`, `shadows.py`, `ops.py`)

Buckets, over ~211 discrete behaviors across 36 handlers: already-pinned 190 / ambiguity-pinned 17 / mismatch-revised 4. 485 → 485 lines (all edits in-paragraph).

- §2.10 counter discipline — revise — mismatch — the blanket "`control_debt_index` is 0.00 whenever the gate is not `CONDITIONS_ISSUED`" now carries the one deliberate exception: a just-reopened gate sits in `IN_REVIEW` carrying its stashed `debt_before_clear` — `routes/review_gates.py:222-226`
- §2.11 reconciliation — insert — ambiguity — the summary carries exactly eight fields and nothing else; defined `inventory_count`, `open_incident_count` (`OPEN`/`ESCALATED`), `unapproved_shadow_count` (`DISCOVERED`/`GRACE_GRANTED`); pinned that a filtered read scopes **every** quantity to the filtered use-case id set (gates/entries/incidents by `use_case_id`, shadows by `claimed_use_case_id`) and that unattributed shadows are therefore counted only by the unfiltered read — `routes/ops.py:44-72`
- §2.5 clock — insert — ambiguity — the clock-set response's `data` carries exactly one field, `current_utc` — `routes/ops.py:83`
- §3.1 asset revision — insert — ambiguity — the at-least-one-field test reads key presence, so an explicit `null` still performs the revision (running every consequence) while overwriting no attribute — `routes/model_assets.py:82`, `validators.py:204-206`
- §3.1 vendor assessment filing — insert — ambiguity — lands with `version` 1 and `decision_rationale`/`decided_by_user_id`/`decided_at` null; the filing endpoint does not itself test the asset's `is_third_party` flag — `routes/model_assets.py:180-186`
- §3.3 take-up — insert — ambiguity — a disallowed **parent** status is refused `ERR_GATE_NOT_IN_REVIEWABLE_STATE` (409), tested after the gate's own status and before the step-27 ownership check — `routes/review_gates.py:53-60`
- §3.3 control-debt paragraph — revise — mismatch — "contributes exactly 0.00" qualified with "the sole exception being a reopened gate, which sits in `IN_REVIEW` carrying the debt restored from its `debt_before_clear`" — `routes/review_gates.py:222-226`
- §3.3 clearance — insert — ambiguity — clearance leaves the `conditions` array itself standing on the row unaltered — `routes/review_gates.py:174-190`
- §3.3 reopening (first clause) — insert — ambiguity — parent-status violation error id + precedence (after the gate's own `CLEARED` requirement), and `debt_before_clear` is left standing at that figure rather than zeroed — `routes/review_gates.py:213-226`
- §3.3 reopening (second clause) — revise — mismatch — replaced "the restored `open_condition_count` is whatever the restored debt implies" with: conditions untouched, `open_condition_count` goes to 0 regardless, making a reopened gate the one place a non-zero `control_debt_index` coexists with an `open_condition_count` of 0 — `routes/review_gates.py:224-226`
- §3.4 scheduling — insert — ambiguity — the use case and the binding are never cross-checked against each other and the binding need not be `PINNED`; record lands with `version` 1 and null result fields — `routes/evaluations.py:25-74`
- §3.4 completion — insert — ambiguity — metric values get no range check; `sample_size` is a non-negative integer; the two non-profile metric fields stay optional and are stored whenever supplied — `routes/evaluations.py:123`
- §3.6 notice withdrawal — insert — ambiguity — a non-owner `Requester` gets `ERR_UNAUTHORIZED` (403) as soon as `{id}` resolves — before the step-10 terminal check and before the `PUBLISHED` test — `routes/notices.py:27-31`
- §3.8 incident creation — insert — ambiguity — lands with `version` 1 and `contained_at`/`resolved_at` null — `routes/incidents.py:61-64`
- §3.8 containment — insert — ambiguity — a `SecurityReviewer` containing an `ESCALATED` incident is refused `ERR_UNAUTHORIZED` (403), tested after the step-17 status check — `routes/incidents.py:116-118`
- §3.9 shadow recording — insert — ambiguity — lands with `version` 1 and `retired_at` null — `routes/shadows.py:45-57`
- §3.9 linking — revise — mismatch — linking is permitted from `DISCOVERED`, `GRACE_GRANTED` **or `LINKED`** (only the terminal `RETIRED`/`ENFORCED_BLOCK` pair is barred), matching §2.9 step 18 — `routes/shadows.py:17-22,104`
- §3.9 sweep intro — insert — ambiguity — the five counters are the whole response and each is defined; an already-`RESTRICTED` asset is not counted again by `assets_restricted` — `routes/ops.py:89-166`
- §3.9 sweep step 2 — insert — ambiguity — step 2 leaves `reassessment_status` exactly where it stood, so a use case opened `IN_PROGRESS` by step 1 and suspended by step 2 reads `SUSPENDED` with `reassessment_status` still `IN_PROGRESS` — `routes/ops.py:110-124`
- §3.9 sweep step 3 — insert — ambiguity — the asset's `version` bumps by exactly 1 for the enforcement whether or not the restriction fires with it, never twice — `routes/ops.py:147-156`
- §3.9 sweep step 3 — insert — ambiguity — the `SHADOW_ENFORCED` entry is appended as hop 1 completes, so it precedes that use case's hop-3 `VENDOR_ASSESSMENT_EXPIRED` entries in ledger order — `routes/ops.py:136-154`

Pass C's three headline findings: (1) the implementation generator's report on `GET /inventory-summary` filter scoping is accurate — every aggregate is scoped to the filtered use-case id set, with the conservation-invariant rationale stated in a code comment, and the previously-unnoticed corollary is that shadows with a null `claimed_use_case_id` fall out of every filtered read; (2) a genuine internal PRD contradiction was resolved — §2.10 and §3.3 both asserted `control_debt_index` is 0.00 outside `CONDITIONS_ISSUED` while §2.11's debt-neutrality invariant and the reopen handler both require a reopened `IN_REVIEW` gate to carry restored debt, so the two blanket statements were revised rather than the invariant; (3) §3.9's link precondition was a state-set mismatch, not a silence — impl permits re-linking from `LINKED`. Deliberately left under-determined: no length bounds on `provider`/`model_name`, no per-condition string bound beyond the 1–20 array size, and the `SHADOW_ENFORCED` skip on a dangling `claimed_use_case_id`.

### Step 9 totals and orchestrator verification

Across the three passes: **43 PRD edits** — 34 ambiguity-pins and 8 mismatch-revisions (plus 1 counted in both buckets by adjacent hunks) — over ~345 classified implementation behaviors.

Orchestrator-side verification: `PRD_COMPLETED.md` is 485 lines / 123 079 bytes versus `PRD_FINALIZED.md`'s 484 lines / 110 355 bytes — **+12 724 chars, 93 changed lines**, so the scan demonstrably ran and did not return a byte-identical copy (the known single-pass Step 9 failure mode this partitioning was chosen to avoid). Document structure is intact: 28 `^#` headings and all 39 `^| \`ERR_` rows still present, and the file still ends at the completed final table row `| \`ERR_PORTFOLIO_REACH_CAP_EXCEEDED\` | 422 |`.

`find workspace/implementation -name '*.py' -newer workspace/implementation/results.1.json` returns empty — no implementation file was modified after the green sweep, so Step 7's 8/8 × 142/142 result still describes the delivered `implementation/`. Steps 8 and 9 touched documentation only.

## PIPELINE COMPLETE — 2026-09-03T04:50:00.000Z

All nine steps finished. Final deliverables in place: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (9 files), `test_suite/` (conftest + 7 modules, 142 collected tests), `workspace/INSTRUCTION.md`, `workspace/PRD.md`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`, `workspace/implementation/` (25 files, 3682 lines) and `workspace/implementation/results.{1..8}.json` (all 142/142).
