# Worklog — task_2492_mine_reclamation_bonding_permit_compliance

## Step 1: Create task directory — 2026-09-03T00:00:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2492_mine_reclamation_bonding_permit_compliance` and its `workspace/` subdirectory. Index 2492 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T02:42:27.679Z

All three scaffold artifacts are complete and the lint is clean.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2492_mine_reclamation_bonding_permit_compliance/`)
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

**Lint**: `VERDICT: clean lint` — 74 endpoints, 11 entities, 18 §1.8 instances, 69 recipe-bearing §1.9 instances, 941 calls scanned, 0 FK reverse-reachability violations.

**SCAFFOLD.yaml surface**: `domain_name: mine-reclamation-bonding`, `api_prefix: /mining`, `difficulty_level: expert_plus`. 11 entities (Operator, MineSite, InspectorProfile, Permit, ReclamationCostEstimate, BondInstrument, BondReleaseApplication, Inspection, ViolationNotice, PermitRevision, ForfeitureProceeding), 12 state machines (Permit and ViolationNotice each two-dimensional; Operator/MineSite dimension machines), 9 calculations, 2 §1.2.1 OCC rules, a 15-priority validation ladder, 74 endpoints, 58 error codes, 6 roles (segregation_of_duties model). Logical clock endpoint `POST /mining/_clock/set_current_utc`, default `2026-08-01T00:00:00Z`.

**§1.8 — 9 rule ids × 2 instances = 18**: `dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`.

**§1.9 — 9 sections, 87 instances (69 real + 18 `excluded_because` stubs)**: entities 12, state_machines 13, calculations 12, validations 11, endpoints 6, errors 23, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1. Audited: all 58 error codes are triggered (real instance or a stub citing a §1.8 instance by name), all stub targets resolve, all instance names globally unique, no forbidden concurrency vocabulary.

**Design adjudications**
- Single `/mining` prefix as the state-program umbrella rather than per-aggregate prefixes.
- Enum/constraint reconciliations during generation: GRAZING→RANGELAND, SENIOR/LEAD→CERT_I/II/III, inspection FAIL→VIOLATIONS_FOUND, ORDINARY→NON_COMPLIANCE, points ranges widened to 0..40 / 0..30 / 0..25, `good_faith_level` RAPID|PARTIAL|NONE.
- `bond_held_amount` description corrected this session: the sum is maintained from the first instrument acceptance onward (not only for ISSUED/RECLAMATION_PHASE), because the priority-15 issuance gate reads it while the permit is still APPLICATION_SUBMITTED.
- Confirmed the `replaces_instrument_id` validity check lives on the PROPOSED→ACCEPTED transition, so ERR_SUBSTITUTION_TARGET_INVALID is exercised at `/accept` (priority 14), not at creation.
- BOND_DEFICIENT is reached without touching money by approving an EXPANSION revision (60 ac → required 1298997.00 vs 900000.00 held); the same lever, at 120 ac (required 1731400.00, admin fee capped at 25000.00), is what makes ERR_RELEASE_EXCEEDS_AVAILABLE reachable at decision time since `requested_amount` freezes at creation.
- bs-001 accepts instruments / bs-002 decides releases, so the SoD rule at priority 7 never blocks the positive paths and gets its own dedicated denial instance.
- For the priority pair, ERR_UNABATED_VIOLATION (priority 11) is deliberately paired against ERR_NOTICE_PERIOD_NOT_ELAPSED (priority 12) using an unabated notice rather than a cessation order.
- Second acceptance of an ACCEPTED estimate requires a re-read of `permit.version` first, otherwise priority 8 (ERR_STALE_PERMIT_VERSION) masks the intended priority-9 ERR_ESTIMATE_STATE_INVALID; both OCC instances exploit that ordering deliberately.
- The cessation threshold boundary (70 vs 69 points) uses two separate operators because `history_points` accrue per operator and would otherwise contaminate the second measurement.

## Step 3: Copy shared files — 2026-09-03T02:42:27.679Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T02:56:40.000Z

All verification is complete. Final state of the deliverable and reports.

## Deliverable

`/home/ubuntu/github/CodingPRD/tasks/task_2492_mine_reclamation_bonding_permit_compliance/workspace/PRD.md`

- **Final line count: 454**
- **Last section heading (exact): `## 5. Error Code Catalogue`**
- **Tail check: PASS** — the file ends at a real section boundary on a complete table row, `| \`ERR_DECISION_REASON_REQUIRED\` | 422 |`, with no trailing audit footer or commentary.
- Section map: §1 Introduction; §2 with 11 subsections (2.1 Regulatory Actors and RBAC, 2.2 API Response Structure verbatim, 2.3 Pagination, 2.4 Resource Identity/Versioning/Logical Clock, 2.5 The Order in Which a Request Is Rejected, 2.6 Monetary Precision and the Rounding Discipline, 2.7 The Bond Ledger and the Deficiency Figure, 2.8 Compliance Posture, 2.9 Guarding Bond Determinations Against Stale Reads, 2.10 Segregation of Duties, 2.11 Cascade Discipline and Reverse-Discovery Reads); §3 with 8 workflow subsections; §4 Endpoint Definitions; §5 Error Code Catalogue.

## Hard Contract 1 — Field-Name Coverage: PASS

Second (post-repair) pass, extracted mechanically from SCAFFOLD.yaml and diffed against every backtick token in the PRD:

| Source set | Required | Missing |
|---|---|---|
| `entities[].fields[].name` | 123 | 0 |
| Write-endpoint `input` identifiers | 77 | 0 |
| GET query/path parameters | 26 | 0 |
| `roles[].role` names | 6 | 0 |
| `errors[].error_id` | 58 | 0 |

(The only unmatched token in the raw grep was `ERR_XXX`, which is the placeholder inside the scaffold's own `response_envelope` template, not a real error code.)

## Hard Contract 2 — Rule Coverage: PASS

- **State machines**: 12/12 documented; 58/58 transitions expressed, and every `from`/`to` state token appears verbatim (0 missing). Includes both parallel pairs (`Permit.status` × `Permit.compliance_posture`, `ViolationNotice.notice_status` × `penalty_status`) and both cyclic machines (PermitRevision `SUBMITTED`↔`INFO_REQUESTED`, BondReleaseApplication `SUBMITTED`→`PUBLIC_NOTICE`→`SUSPENDED`→`SUBMITTED`).
- **Calculations**: 9/9 documented as numbered prose steps with normative rounding order. Every numeric constant across all 9 (`INDIRECT_COST_RATE`, `SURETY_RATING_MULTIPLIER`, `COLLATERAL_HAIRCUT`, `PHASE_RELEASE_PCT`/`PHASE_RETENTION_RATE`, `DOLLARS_PER_POINT`, `GOOD_FAITH_RATE`, credit caps, `HISTORY_*`, `HAZARD_WEIGHT`, weights and caps, self-bond thresholds and rates, admin-fee floor/ceiling, `STATUTORY_MINIMUM_BOND`) verified present — 0 gaps.
- **Validation ladder**: 42 entries across all 15 priorities, each with its error id and its `applies_to` scope. All 11 operations in the Operator role's `exclusive_operations` list now carry an explicit ownership statement, and both Inspector-scoped operations carry `ERR_NOT_ASSIGNED_INSPECTOR`.
- **Concurrency**: both OCC rules stated with write endpoint, `expected_permit_version`, `ERR_STALE_PERMIT_VERSION`, HTTP 412.
- **Priority inversions** called out explicitly: priority 11 `ERR_UNABATED_VIOLATION` beats priority 12 `ERR_NOTICE_PERIOD_NOT_ELAPSED`; priority 8 `ERR_STALE_PERMIT_VERSION` beats priority 9 `ERR_ESTIMATE_STATE_INVALID`.
- Two gaps found during the audit were repaired before this pass: the priority-6 ownership check on estimate creation (§3.2) and on bond-instrument proposal (§3.3).

## Hard Contract 3 — §3 Path Purity: PASS

1062 backtick tokens scanned in §3: 0 starting with `/`, 0 bare HTTP-method tokens, 0 method+path combinations. Endpoints are referenced only via state-transition framing, role+action verbs, or capability descriptions.

## Coverage audit vs SCAFFOLD.yaml

| Artifact | Scaffold | PRD |
|---|---|---|
| Entities | 11 | 11 |
| Endpoints | 74 | 74 rows in §4 |
| State machines / transitions | 12 / 58 | 12 / 58 |
| Calculations | 9 | 9 |
| Validation priorities / entries | 15 / 42 | 15 / 42 |
| Error codes | 58 | 58 rows in §5 |
| Roles | 6 | 6 |

## Two adjudications you should know about

1. **`PUBLIC_NOTICE_DAYS` and `CONTEST_WINDOW_DAYS` have no value anywhere in SCAFFOLD.yaml.** They are referenced by `notice_end_date`, `contest_deadline`, the notice-window conflict rule, and the forfeiture-creation side effect, but never assigned. Grep of the scaffold and a read of `worklog.md` confirmed the numbers are absent; the values presumably live only in the two withheld design files, which I did not open. I set **both to 30 days** and stated that explicitly in the PRD so the implementer has a deterministic figure. If the design files use different numbers, the generated tests will disagree with the PRD on these two windows — worth checking at the test-generation step.
2. **`PermitRevision.round_count` is self-contradictory in the scaffold.** §1.1 gives `default: 1`; the `POST /mining/permit-revisions` side effects say `round_count 0`. I documented **1**, because §1.1 is the canonical field-level spec and because 1 combined with the priority-13 cap ("strictly below 2") coherently permits exactly one resubmit.

Also noted: the scaffold's validation rules refer to an `X-Role` header, but SKILL.md mandates `X-User-ID` / `X-User-Role`. The PRD uses `X-User-Role` throughout per the skill's hard contract.

The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

**Orchestrator verification of Step 4**: independently confirmed `wc -l` = 454, tail ends on the final complete error-table row, and §5 contains exactly 58 `ERR_` rows — the PRD is not truncated. Also independently grepped all three scaffold files for `PUBLIC_NOTICE_DAYS` / `CONTEST_WINDOW_DAYS`: the constants are unassigned in the design indices too, not merely in SCAFFOLD.yaml, so the doc generator's choice of thirty days for both is not in conflict with any withheld value and the PRD's stated "thirty days" is the single authority for the test generator's PRD-first filter. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T04:36:00.000Z

Steps 5 and 6 were launched concurrently in a single assistant message, so the implementation generator's process could not see `test_suite/` (the directory did not exist at its spawn time) and the test generator could not see `implementation/`.

Suite generation for task 2492 is complete. Final state:

## Files

**`.../test_helpers/` (9 files, Stage 1)** — `__init__.py`, `api_client.py` (one method per PRD endpoint under `/mining`), `api_errors.py` (58 codes + HTTP status map), `assertions.py` (entity + ledger + violation-point invariants), `constants.py`, `factories.py`, `fixtures.py` (chain_applied → chain_estimate_accepted → chain_bond_posted → chain_issued and the release/notice/penalty/forfeiture/legacy setups), `test_users.py` (six roles, `bs-001` accepter / `bs-002` decider), `types.py`.

**`.../test_suite/` (12 files, Stage 2)** — `conftest.py` plus:

| file | tests |
|---|---|
| test_01_registry_and_permit_intake | 12 |
| test_02_bond_determination | 8 |
| test_03_self_bonding_financial_tests | 6 |
| test_04_bond_instruments_and_credit | 12 |
| test_05_permit_issuance | 5 |
| test_06_permit_lifecycle_and_revisions | 8 |
| test_07_bond_release_notice_and_comment | 9 |
| test_08_bond_release_decision_and_rescission | 9 |
| test_09_inspections_and_enforcement | 19 |
| test_10_forfeiture_and_legacy_funding | 10 |
| test_11_concurrency_and_access_control | 6 (new this session) |

104 test functions, 112 collected items (one parametrized not-found test expands to 9). `pytest --collect-only` is clean.

## Design-index coverage (audited programmatically against both yamls)

- **Queue A (§1.8 Difficulty): 18/18 instances, all with ≥2 tagged tests** — 36 of the 104 tests carry Difficulty tags.
- **Queue B (§1.9 Corner): 68 of 69 non-stub instances covered** (the 18 `excluded_because:` stubs were not translated).
- Every `Design:` line resolves to a real instance in the correct section; no untagged, dual-tagged, or stub-tagged tests.

## Instance skipped (1)

`Corner/errors/release_approval_above_recomputed_headroom_rejected` — **design/PRD contradiction, outcome not uniquely derivable** (not PRD silence). Issuance guarantees `held ≥ required` and filing caps `requested_amount` at `0.6 × bond_required`, so the priority-15 headroom gate can only bite once `bond_deficiency_amount > 0`; §2.8 then drives the `PUBLIC_NOTICE` application to `SUSPENDED`, so the decide call must report own-state `ERR_RELEASE_STATE_INVALID` at priority 9. The design's own assertion "status == PUBLIC_NOTICE" contradicts the PRD, so no test was emitted (no weakening, no xfail, no placeholder).

## Adjudications

1. `PUBLIC_NOTICE_DAYS` / `CONTEST_WINDOW_DAYS` = **30** per the PRD (as instructed); `contest_deadline` verified as `2026-08-31T00:00:00`.
2. `round_count` starts at 1, so exactly one admissible resubmit (1 → 2) before `ERR_REVISION_ROUND_LIMIT`.
3. Pre-acceptance permit money fields are `0.00` with `bond_basis` `FULL_PLAN` (PRD §3.2), not null as one corner recipe implied.
4. Header name is `X-User-Role` (PRD §2.1), not the corner design's "X-Role".
5. Timestamp equality asserted as `startswith("…T00:00:00")` prefix checks (PRD pins the instant, not the serialisation suffix).
6. After a 129899.70 PHASE_I approval the posture is `BOND_DEFICIENT` (deficiency 95897.70), correcting a design recipe that asserted `COMPLIANT`.
7. Zero-disturbed-acres cease-mining refusal is `ERR_PERMIT_STATE_INVALID` (uniquely derived from §3.4).
8. The design's 20-acre `bond_required 144700.00` looked wrong (7110.00 × 20 + 1.5% = 144333.00) but is correct once §3.2's **2500.00 administrative-fee floor** applies — no change needed.

## Cleanups this session

- Removed an unused `PERMIT_REVIEWER` import from `test_04`.
- Rewrote six docstring citations that had been paraphrased so all 104 are now verbatim, greppable PRD text (verified by an automated substring pass against `workspace/PRD.md`): three priority-ladder items in `test_01`, the estimate-payload sentence (restored its elided em-dash clause), and the `compliance_posture` second-dimension sentence in `test_06`.
- No occurrence of "scaffold" or scaffold section references anywhere in `test_suite/` or `test_helpers/`.

I did not run an execution sweep: that is Step 7's job, and the host currently has eight concurrent sweeps running for task 2500. One exploratory run I started was invalid (relative `--start-command` breaks the per-test server restart) and has been killed; no stale server or port-registry entry remains.

## Step 6: Generate implementation — 2026-09-03T04:36:00.000Z

Implementation complete and verified.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2492_mine_reclamation_bonding_permit_compliance/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `app.py` | 89 | Flask factory, 12 blueprint registrations, `ApiError`/404/405/`HTTPException`/`Exception` handlers, `__main__` on `$PORT` (default 10000) |
| `constants.py` | 290 | enums, role sets, rate/points/threshold tables |
| `errors.py` | 85 | 58-entry `ERROR_STATUS` map, `ApiError`, `fail()`, `invalid()` |
| `db.py` | 126 | in-memory `Store` (11 dicts + logical clock + `_seq`), `Decimal` money helpers, id/timestamp helpers |
| `validation.py` | 236 | bands 1–5 primitives (`authorize`, typed field readers, `pagination`, `lookup`, `resolve`) |
| `calculations.py` | 301 | all 9 PRD calculations |
| `engine.py` | 257 | cross-entity cascades (bond ledger, posture, suspension propagation, termination, forfeiture cascade, legacy reclassification, `bump`) |
| `serialization.py` | 258 | one `*_out` per entity; 4 figures derived on read |
| `response.py` | 67 | envelope builders (`object`/`created`/`list`/`error`) + `paginate` |
| `routes/_shared.py` | 116 | filter/paging helpers, ownership/state guards, denial-reason split |
| `routes/*.py` (12 modules) | 19–353 each, 2 062 total | the 74 endpoints |
| `requirements.txt`, `start.sh` | 1, 16 | `flask>=3.0`; launcher `cd`s to its own dir, installs Flask only if absent, `exec python3 app.py` |

**3 970 lines total. 74 endpoints registered — exact path/method match with the PRD §4 table.**

## Structure

- **Validation ladder** — the 15 PRD bands are encoded as *statement order* inside each handler, never as a generic decorator stack, so each endpoint's short-circuit sequence is auditable line-by-line. Bands 1–5 come from `validation.py` helpers (`authorize` → typed readers → `lookup` for path ids → `resolve` for body FKs, with FK resolution order taken from the scaffold: `mine_site_id` before `operator_id`, `permit_id` before `inspector_id`/`replaces_instrument_id`); bands 6–15 are explicit guards in the handler body.
- **State machines** — 12 machines; parallel dimensions (`Permit.status` × `compliance_posture`, `ViolationNotice.notice_status` × `penalty_status`) are separate fields with separate guards. Posture is a pure function of the permit's facts (`engine.compute_posture`, 5 precedence bands) recomputed after every mutation rather than assigned per-transition, which makes suspension propagation, TERMINATED bubble-up and the 4-link forfeiture cascade fall out automatically.
- **Calculations** — `decimal.Decimal` + `ROUND_HALF_UP` quantized at every *named* step in the PRD's stated order (never deferred or hoisted); points arithmetic is pure `int`. All temporal logic reads the logical clock, including `created_at`/`updated_at`.
- **Version discipline** — every write goes through `engine.bump()`, which uses a per-request `flask.g` set so a row's `version` moves by exactly 1 no matter how many cascade links touch it.

## Verification

- Fresh boot via `PORT=18492 bash start.sh`: store empty (`total_count: 0`), clock defaults to `2026-08-01T00:00:00Z`.
- `grep` confirms zero `open()`/`sqlite3`/`pickle`/`/tmp` usage — memory only, nothing seeded.
- A 120-request in-process smoke test covering the full lifecycle (operator → financial test → site → permit → estimate + OCC → instrument → issue → disturbance → cease-mining → release notice/comment/objections/approve/rescind → violation notice → cessation → penalty assess/pay → abate → revision info-request/resubmit/round-limit → forfeiture initiate/contest/finalize/state-reclamation → legacy nomination/queue/award) passes, including 24 deliberate ladder short-circuits. Bond math checks out end-to-end (`1 202 775.00` required, `481 110.00` PHASE_I retention floor, `360 832.50` release, `4 620.00` penalty, `20.00` legacy priority score) and edge HTTP cases return the standard envelope (unknown path 404 `ERR_NOT_FOUND`, bad method 405, malformed JSON 422).
- Three smoke expectations of mine were wrong, not the code: cumulative-acres is measured against *released* acreage (not pending applications), and six error ids are 403/409 rather than 422 per the PRD status table. Corrected the test, not the implementation.

## PRD ambiguities resolved

1. Auth header is `X-User-Role` (PRD) not the scaffold's `X-Role`; **role authority is exclusive, not hierarchical** — each endpoint's role list transcribed individually (e.g. `GET /mining/operators` excludes Operator *and* Inspector).
2. `PermitRevision.round_count` starts at **1**; `resubmit` requires `round_count < 2`.
3. `bond_held_amount = Σ credited(ACCEPTED) − bond_released_to_date`, with recomputation skipped on TERMINATED/FORFEITED so it can never go negative.
4. Four figures (`self_bond_exposure_amount`, `violation_points_total`, `outstanding_penalty_balance`, `scheduled_inspection_count`) are derived on read — no stored value, no version bump.
5. Permit version bumps only when a permit field genuinely moved (`sync_posture`, `publish-notice`'s `last_notice_end_date`); release **DENY** touches no permit field and does not bump it, per §249.
6. Notice-window conflict iff `now < other.notice_end_date + 15d` for apps in {PUBLIC_NOTICE, APPROVED} — exactly 15 days is allowed. Inspector double-booking iff `new_start < other_end and other_start < new_end` — abutment allowed.
7. Explicit JSON `null` is treated as absent for optional/type-conditional fields; empty-string `denial_reason` yields `ERR_DECISION_REASON_REQUIRED` (band 13), not `ERR_INVALID_REQUEST`.
8. Dimension-check order where the PRD is silent: `assess-penalty` checks `penalty_status` then `notice_status`; `vacate` the reverse; forfeiture creation checks permit status before `ERR_PERMIT_HAS_OPEN_PROCEEDING`.
9. `PATCH /operators/{id}/financials` gates on `registry_status == DISQUALIFIED`; `POST /financial-test` gates on `self_bond_status == DISQUALIFIED`.
10. Unbounded numerics validated `ge=0` (`award_amount`, `unfunded_reclamation_need`, `acres_affected`, `collateral_market_value`, `state_reclamation_cost_estimate`, `actual_cost_incurred`, `amount_paid`); HTTP 201 only for the 11 creation POSTs.

`test_suite/` and `test_helpers/` were never read or listed.

## Step 7: Run tests and iterate — 2026-09-03T05:15:00.000Z

All 8 parallel rounds green: 112/112 passed, 0 failed, 0 errors, 0 skipped.

## Summary

**Iterations run:** 2 (baseline sweep, then one fix batch + confirming sweep).

Iteration 1 was fully deterministic — the *same* 4 tests failed in all 8 rounds, with no flakiness and no load-induced timeouts or connection resets. All 4 traced to a single root cause.

**Tests deleted:** none. No test asserted a scaffold-only rule, and no test's rule was absent from the PRD.

**Fixes applied to `test_helpers/`:** none. The fixture chains construct PRD-faithful preconditions throughout; the bug was in assertions, not setup.

**Fixes applied to `implementation/`:** none. The implementation was correct on all 4 failures.

**Fixes applied to `test_suite/`** (STEP 1c partial-coverage split — 7 assertions across 2 files):

- `test_07_bond_release_notice_and_comment.py` — `test_a_notice_window_opening_inside_the_fifteen_day_buffer_is_refused`, `test_a_notice_window_opening_exactly_fifteen_days_later_is_admitted`, `test_republishing_a_notice_already_out_is_refused`
- `test_08_bond_release_decision_and_rescission.py` — `test_an_unabated_violation_outranks_the_unelapsed_notice_period`

All four asserted `notice_start_date`/`notice_end_date`/`last_notice_end_date` as exact bare-date strings (`== "2026-08-31"`) against an implementation rendering full instants (`"2026-08-31T00:00:00.000Z"`).

### Why this was a test bug, not an implementation bug

**Coverage (1a) held** for the *value*. PRD §3.5 verbatim: "On success, `notice_start_date` is set to the logical clock's current value, `notice_end_date` is set to thirty days after `notice_start_date`, the permit's `last_notice_end_date` is recomputed…"

**Unique derivability (1b) failed** for the *rendering*. PRD pins a serialization format for exactly two things — §2.4 `created_at`/`updated_at` ("rendered with three fractional digits") and §2.2 `api_request_timestamp`. It says nothing about these three fields, admitting two PRD-faithful readings: the full clock instant (§2.4 fixes the clock at `2026-08-01T00:00:00Z`, so "the logical clock's current value" *is* an instant), or a calendar date inferred from the `_date` suffix.

Two independent signals confirm the instant reading is the more faithful one, so the implementation should not have been changed:
1. §3.5's priority-12 gate — "the logical clock's current instant must be **strictly after** the application's `notice_end_date`" — requires instant-granularity comparison to be well-defined.
2. The suite already avoids asserting rendering for structurally identical fields: `abatement_deadline` uses `.startswith("2026-08-31")` and `contest_deadline` uses `.startswith("2026-08-31T00:00:00")`, both described by PRD in the same "N days after <stamp>" form. The four failing assertions were the sole inconsistency.

I therefore kept the covered assertion (the exact calendar day) and dropped only the PRD-silent rendering, normalizing to the `.startswith(...)` convention the suite had already established. Boundary strength is fully preserved — the 15-day closed-interval buffer still distinguishes `2026-09-14` (refused) from `2026-09-15` (admitted), and every `is None` window-cleared assertion is untouched. No error_id assertion was downgraded, no skip/xfail added.

**Orchestrator verification of Step 7**: independently re-read all eight `workspace/implementation/results.{1..8}.json` (all present, all written at the same sweep timestamp) and confirmed each reports `total 112 / passed 112 / failed 0 / errors 0 / skipped 0`. The green sweep is real, not a subagent claim.

**Step 8 skip-condition adjudication (orchestrator)**: Step 7 reported 0 deletions, 0 `test_helpers/` fixes and 0 `implementation/` fixes, but **7 `test_suite/` assertion fixes**. The skip condition requires all four counts to be zero, so Step 8 is NOT skipped. The substantive reason to run it: the fix batch's root cause was a genuine PRD silence — the PRD never states the serialization of `notice_start_date`, `notice_end_date` and `last_notice_end_date`, and the implementation resolved that silence by rendering full instants. That is exactly the class of implementation-pinned choice Step 8 exists to write back into the PRD.

## Step 8: Finalize PRD — 2026-09-03T05:10:00.000Z

Done. `PRD_FINALIZED.md` written with a single edit.

## Line counts
- `PRD.md`: 454 lines / 99,288 bytes
- `PRD_FINALIZED.md`: 454 lines / 100,105 bytes
- Line delta: 0 (0.0%); byte delta: +817 (+0.82%) — one sentence inserted mid-paragraph, no new sections.

## Changes
- **§2.4 (Resource Identity, Versioning, and the Logical Clock)** — *insert* — after the existing `created_at`/`updated_at` rendering sentence, added one sentence pinning that **every** temporal value the server returns is rendered in that same shape (full ISO 8601 UTC instant, three fractional digits, trailing `Z`, time-of-day preserved rather than reduced to a bare calendar date), explicitly enumerating the `*_at` stamps, the inspection window bounds, the `*_date` fields, the derived deadlines, and the clock endpoint's `current_utc` echo; plus that a temporal field holding no value renders as null — `implementation/db.py:103-116` (`fmt_ts`), applied at `implementation/serialization.py:20-21,90,103-104,117,120,140,155-156,162,176,178,182,200,206-209,231,244,251-252` and `implementation/routes/clock.py:19`.

No other edit was warranted: the Step 7 diff reports zero implementation fixes, zero `test_helpers/` fixes, and zero test deletions, and its seven test-side edits all trace to this single rendering silence.

## Pre-edit search log

**Edit 1 — §2.4 temporal rendering**
- **(a) Subject identified:** the serialization/rendering format of every date- or timestamp-valued field in any response body — not just `notice_start_date` / `notice_end_date` / `last_notice_end_date`.
- **(b) Impl paths enumerated:** `grep -rn "isoformat\|strftime\|fmt_ts\|%02d"` over the whole implementation returned the complete formatter set. Read `implementation/db.py` (`fmt_ts` — the sole row-field formatter; `astimezone(utc)`, `%03d` fractional digits, `Z` suffix, `None → None`), all 24 `fmt_ts` callsites in `implementation/serialization.py` across all eleven entity projections, `implementation/routes/clock.py:19` (`current_utc` echo also goes through `fmt_ts`), and `implementation/response.py:11-27` (`api_request_timestamp` uses a second, byte-identical format string, already pinned by PRD §2.2 — consistent, so no §2.2 edit needed). Also read `implementation/validation.py:parse_iso` (input side: bare dates and `Z` suffixes both parse, naive inputs assumed UTC) to confirm the stored values that feed `fmt_ts`, and `implementation/engine.py:117-163` plus `implementation/routes/releases.py:124-136,224,309` to confirm `notice_end_date = start + 30 days`, `last_notice_end_date = max(non-suspended notice_end_date)`, and the clear-to-null paths — all consistent with the PRD's existing §2.8/§3.5 prose, which I left verbatim.
- **(c) Wording adjustments made:** (i) enumerated the fields explicitly rather than leaning on an `*_at`/`*_date` naming heuristic, so the universal claim is backed by the grep rather than by a naming convention; (ii) added the explicit null clause to match `fmt_ts`'s `None` short-circuit; (iii) initially wrote "never an instant truncated to midnight", then revised to "preserving whatever time-of-day the stored value carries instead of being reduced to a bare calendar date" — the first phrasing could be misread as forbidding a midnight rendering, which the impl legitimately emits whenever a client supplies a bare date for `estimate_effective_date` / `proposed_start_date` or leaves the clock at its `2026-08-01T00:00:00Z` default; (iv) deliberately did *not* pin sub-millisecond truncation (`microsecond // 1000`) — outside the Step 7 root cause and unexercised, so left under-determined per the no-new-mismatch preference.

## Step 9: Complete PRD — 2026-09-03T05:24:00.000Z

`workspace/PRD_COMPLETED.md` is written. All 28 changed lines are in-paragraph replacements — no new sections, no new paragraphs, no changes to the §4 endpoint table or §5 catalogue rows.

**Counts** — source `PRD_FINALIZED.md`: 454 lines / 100,148 chars. `PRD_COMPLETED.md`: 454 lines / 107,040 chars (+6,892 chars). 29 changes across 28 lines: **23 ambiguity-pins, 6 mismatch-revisions**.

**Changes**

- §2.1 — insert — ambiguity — whitespace-only header value counts as empty for `ERR_MISSING_AUTH_HEADERS` — `validation.py:30`
- §2.3 — insert — ambiguity — `created_at` ties broken by server insertion order — `db.py:126`
- §2.4 — insert — ambiguity — a row is stamped at most once per request even across cascade links — `engine.py:22-32`
- §2.5 band 3 — insert — ambiguity — names the nine fields bounded at ≥0 rather than >0; whitespace-only required strings and empty query filters rejected; undeclared body fields ignored — `validation.py:70-137`
- §2.5 band 5 — insert — ambiguity — per-endpoint reference resolution order (`mine_site_id`→`operator_id`, `permit_id`→`replaces_instrument_id`, `permit_id`→`inspector_id`); query-string id filters are never existence-checked — `permits.py:61`, `instruments.py:75`, `inspections.py:51`, `_shared.py:19`
- §2.6 — insert — ambiguity — money/score/acreage emitted as JSON numbers; integer counters as JSON integers — `serialization.py:12`
- §2.7 — insert — ambiguity — `bond_held_amount` frozen at 0.00 once permit is `TERMINATED`/`FORFEITED`; only deficiency re-derived — `engine.py:52-60`
- §2.8 — revise — **mismatch** — the four notice-driven posture triggers stamp the permit only when `compliance_posture` or `last_notice_end_date` actually moves — `engine.py:108-114`
- §3.1 — insert — **mismatch** — `self_bond_exposure_amount`, `violation_points_total`, `outstanding_penalty_balance`, `scheduled_inspection_count` are read-derived, so changing them does not stamp the owning row — `serialization.py:39-43,77`
- §3.1 — insert — ambiguity — all five financial inputs optional, empty body accepted and still stamps; capacity reset regardless of prior status — `operators.py:71-101`
- §3.2 — revise — **mismatch** — escalation days measured between full instants (truncated), not bare calendar dates — `calculations.py:21`
- §3.2 — revise — **mismatch** — `releasable_amount` is waterfall step four (held less retention floor, floored at 0), unclipped by acreage; six figures only, no common properties — `permits.py:342-352`
- §3.3 — insert — ambiguity — credit fixed before the replaced instrument is retired, so a self-bond substitution prices against headroom still counting the outgoing exposure — `instruments.py:184-192`
- §3.3 — revise — **mismatch** — self-bond acceptance moves exposure but does not stamp/version-bump the operator — `instruments.py:194-196`
- §3.4 — revise — ambiguity — disturbance report admitted only on `ISSUED`/`RECLAMATION_PHASE`; an empty report still stamps — `permits.py:237-249`, `constants.py:177`
- §3.4 — revise — ambiguity — recalculation permit statuses named `ISSUED`/`RECLAMATION_PHASE` — `constants.py:176`
- §3.4 — revise — ambiguity — zero `disturbed_acres` on cease-mining reports `ERR_PERMIT_STATE_INVALID`, after the ownership check — `permits.py:218-225`
- §3.5 — insert — ambiguity — per-acre bond is 0.00 when `disturbed_acres` is zero — `calculations.py:136-139`
- §3.5 — insert — ambiguity — publish-notice stamps the permit only if `last_notice_end_date` changes — `releases.py:134-137`
- §3.5 — revise — ambiguity — comment and resolve-objections both require `PUBLIC_NOTICE`, else `ERR_RELEASE_STATE_INVALID`; `is_objection` required; neither touches the permit — `releases.py:147-169`
- §3.5 — insert — ambiguity — a cleanly terminated permit reads `COMPLIANT` after the post-termination posture recomputation — `releases.py:262-263`
- §3.5 — insert — ambiguity — reinstatement leaves notice dates null and touches no permit field — `releases.py:286-290`
- §3.6 — insert — ambiguity — fractional `duration_hours` honoured to the second when deriving `scheduled_end` — `inspections.py:57`
- §3.6 — insert — ambiguity — on vacatur `notice_status` is checked before `penalty_status`, so a terminal-and-`PAID` notice reports `ERR_NOTICE_STATE_INVALID` — `notices.py:182-187`
- §3.7 — revise — ambiguity — proceeding creation admits `ISSUED`/`RECLAMATION_PHASE` and evaluates the status check before the one-proceeding rule — `forfeitures.py:47-52`
- §3.7 — revise — ambiguity — `completion_pct` accepted as any number, integral or fractional — `forfeitures.py:159`
- §3.7 — revise — **mismatch** — refund credited and operator stamped only when surplus is strictly positive — `forfeitures.py:181-185`
- §3.8 — insert — ambiguity — funding queue's fourth tie-break is server insertion order — `calculations.py:262-269`
- §5 — insert — ambiguity — `ERR_NOT_FOUND` (404) for undefined paths and `ERR_METHOD_NOT_ALLOWED` (405) for undefined methods, both outside the catalogue — `app.py:57-67`

Two impl details I deliberately left unpinned because they are behaviourally indistinguishable from the existing prose: the self-bond headroom floor at zero (identical outcome to the unfloored subtraction at every reachable input), and the ordering of filter-parameter versus pagination validation inside a list read (both yield `ERR_INVALID_REQUEST`).

**Orchestrator verification of Step 9**: confirmed `workspace/PRD_COMPLETED.md` exists (107,040 bytes, 454 lines, tail ends on the final complete §5 error-table row — no truncation), alongside `PRD.md` and `PRD_FINALIZED.md`. Pipeline complete: all nine steps ran, and the final artifact set is `SCAFFOLD.yaml` + both design indices, `test_helpers/` (9 files), `test_suite/` (conftest + 11 test modules, 112 collected items), `workspace/implementation/` (74 endpoints) with `results.{1..8}.json` all green, and PRD / PRD_FINALIZED / PRD_COMPLETED.
