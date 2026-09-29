# Worklog — task_2619_corporate_fitness_center_management

## Step 1: Create task directory — 2026-09-03T20:28:56.265Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2619_corporate_fitness_center_management` and `.../workspace` (pre-assigned path; no index auto-allocation).

## Step 2: Generate scaffold — 2026-09-03T22:14:30.860Z

All three scaffold artifacts for task 2619 are complete and lint-clean.

Files (all under `tasks/task_2619_corporate_fitness_center_management/`):
| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 3509 | 173,942 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2418 | 156,581 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 5732 | 353,475 |

Lint verdict (verbatim):
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2619_corporate_fitness_center_management/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2619_corporate_fitness_center_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2619_corporate_fitness_center_management/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    69
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     63
  Calls scanned (§1.8+§1.9):  1393

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Contents:
- **SCAFFOLD.yaml** (§1.0–§1.7): 13 entities, 69 endpoints, 41 prioritised validations, 67 error ids, 6 roles, 8 state machines, 2 OCC rules, 7 calculations. Profile: `compliance_audit` / `ledger_reconciliation`, layers `dual_variant_calculation` + `cascading_side_effects` + `optimistic_concurrency` + `rate_threshold_triggers`, flat topology, parallel state-machine shape, `segregation_of_duties`, immediate consistency, `difficulty_level: expert_plus`. Contains neither design key (verified via PyYAML).
- **SCAFFOLD_DIFFICULTY_DESIGN.yaml**: single key `scaffold_difficulty_design`, 9 rule_ids × 2 instances = 18 fully-specified recipes.
- **SCAFFOLD_CORNER_DESIGN.yaml**: single key `scaffold_corner_design`, 9 sections (entities 12, state_machines 16, calculations 13, validations 9, endpoints 7, errors 25, rbac 6, cross_cutting_complexity_layers 5, consistency_model 1) = **94 instances, 65 full recipes + 29 `excluded_because` stubs**, all names unique, every stub's `difficulty_instance` resolving to a real §1.8 instance and carrying no `test_recipe`.

Verified breadth invariants:
- Every one of the 67 catalogued error ids is triggered or stub-delegated (0 unmentioned).
- Every one of the 69 declared endpoints is exercised by at least one recipe call (0 uncalled).
- Claim-type coverage spans all rows of the relevant claim-extraction tables per section (entities 12/12 incl. the `flat` topology row; calculations incl. `precision`, `tiered_pricing`, `weighted_scoring`, `variant_*`, `reconciliation`; validations 9/9; endpoints incl. `bulk_action`, `conditional_action`, `cross_reference_link`, `computed_read`; rbac `peer_roles` + `segregation_of_duties`).
- All error-response `captures` use `$.data.error_id` (three earlier ones that captured `$.data.id` on 4xx were corrected).
- Hard constraint respected: no sibling task directory was listed, read, or grepped; the design derives only from the scenario text and the generator skill.

## Step 3: Copy shared files — 2026-09-03T22:15:10.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2619_corporate_fitness_center_management/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T22:34:00.000Z

PRD generation complete.

**Output:** `workspace/PRD.md` — **533 lines**, built incrementally (1 Write + 5 heredoc appends, no chunk near the output cap). Ends at a real boundary: the final row of the §5 error table (`| \`ERR_OPEN_INVOICES\` | 409 |`), no truncation, no audit footer.

Structure: §1 Introduction; §2 Global Specifications with 11 subsections (2.1 roles/headers, 2.2 the fixed response-structure block copied verbatim, 2.3 pagination, 2.4 identity/versioning, 2.5 logical clock, 2.6 flat collections and site containment, 2.7 OCC, 2.8 money/rounding, 2.9 cascade discipline and conserved-quantity invariants, 2.10 health-data privacy, 2.11 the full 41-rule precedence ladder); §3 Business Logic in 9 domain subsections; §4 endpoint table (exactly 4 columns); §5 error table (exactly 2 columns).

**Endpoint and error coverage:** all 69 scaffold paths present as backticked tokens in §4; all 67 error ids present. 0 missing in each. (The scaffold's own `complexity_profile` comment says "66 error codes" — stale; `errors[]` authoritatively holds 67.)

```
Field coverage check:
- entities[].fields: 150 required, 150 present, 0 missing
- endpoints[].request_body / input: 198 required (input + query_params + path_params identifiers), 198 present, 0 missing
- endpoints[].query_params: included in the 198 above, 0 missing
- computed-read output identifiers: 39 required, 39 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 41 checked, 41 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint named by framing + expected_member_version / expected_contract_version + ERR_STALE_MEMBER_VERSION / ERR_STALE_CONTRACT_VERSION all named), 0 missing
- state_machines[].transitions: 78 checked across 14 machines (incl. Member's two parallel dimensions), 78 fully expressed with preconditions and side effects, 0 missing
- calculations[]: 9 checked, 9 fully expressed (session_labor_cost, staff_readiness_index, program_attainment, incentive_points_award, aed_readiness_status, equipment_downtime_credit, coverage_shortfall_penalty, monthly_invoice_amounts, contract_utilization_rollup), 0 missing
- validations[] conditions: 41 checked, 41 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 42 checked, 42 expressed, 0 missing
- entities[].fields[] structured content: 150 checked, 150 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (3 session-cancellation branches; MANAGEMENT_FEE vs COST_PLUS invoicing; provisional vs final attainment; incident CLAIM_FILED vs CLOSED_NO_CLAIM; member eligibility vs access dimensions; room/staff interval semantics), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1191
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- tokens containing any `/` at all: 0
Status: PASS
```

Also verified: no fuzzy hedging words, no pseudocode/formula blocks, no references to the scaffold or its section numbers, and the §2.2 fixed block retains its literal markers. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened or grepped, and no sibling task directory was read.

Deliberate rule collisions whose outcomes the PRD pins down explicitly, since they are the likeliest implementation divergences: unwaived member into a full session returns `ERR_WAIVER_REQUIRED` (not capacity); non-`STAFFED` session start returns `ERR_SESSION_NOT_STAFFED` before the AED and grace-window gates; badge grant on a pending, unwaived member returns `ERR_WAIVER_REQUIRED` (not `ERR_ELIGIBILITY_NOT_VERIFIED`); room conflicts use a closed interval buffered 15 minutes on the end side while staff conflicts use an unbuffered half-open interval; and per-assignment labor rounding yields 9791 cents where naive aggregate rounding yields 9792.

**Orchestrator verification:** `wc -l` = 533; `tail -12` ends on the final error-table row; 5 top-level sections present (§1–§5); no difficulty-instruction leakage found in PRD.md.

## Step 5: Generate unit tests — 2026-09-03T23:15:45.000Z

Stage 1 and Stage 2 are complete. Everything is at the task root; nothing was written under `workspace/`.

## Inventory

`/home/ubuntu/github/CodingPRD/tasks/task_2619_corporate_fitness_center_management/`

**test_helpers/** (9 files, 2 350 lines): `__init__.py` 53, `api_client.py` 302, `api_errors.py` 151, `assertions.py` 299, `constants.py` 88, `factories.py` 226, `fixtures.py` 710, `test_users.py` 58, `types.py` 463.

**test_suite/** (15 files, 10 807 lines): `conftest.py` 81, `test_01_entity_shapes_and_reads.py` 858, `test_02_lifecycle_transitions.py` 887, `test_03_calculations_and_read_models.py` 810, `test_04_input_validation.py` 588, `test_05_endpoint_workflows.py` 870, `test_06_error_conditions_uniqueness_and_guards.py` 1115, `test_07_error_conditions_lifecycle_and_lookups.py` 559, `test_08_role_permissions.py` 641, `test_09_billing_and_attainment_math.py` 577, `test_10_lifecycle_paths_and_cascades.py` 871, `test_11_gate_order_and_thresholds.py` 758, `test_12_cross_entity_state_and_scheduling.py` 741, `test_13_compensating_invariants.py` 805, `test_14_cross_cutting_layers.py` 646.

**162 test functions → 182 collected pytest items.** `ls -la` confirms `test_helpers/` and `test_suite/` at the task root and absent from `workspace/` (which holds only `INSTRUCTION.md`, `PRD.md`, `implementation/` — never opened).

## Coverage against the two design indices

- Queue A: all 18 difficulty instances covered, every one with >=2 tests (18 instances -> 47 tests).
- Queue B: 62 of 63 non-stub corner instances covered with >=1 test; the 31 `excluded_because:` stubs produced no tests, and every stub's `difficulty_instance:` pointer resolves.
- Audit result: 0 untagged tests, 0 dual-tagged tests, 0 tags resolving to a non-existent or stub instance, 0 non-verbatim quoted citation spans (all quotes machine-checked against PRD.md), no `skip`/`skipif`/`xfail`, no occurrence of "scaffold"/"test_recipe"/scaffold section refs anywhere in the emitted code.

## The one gap left as a gap (PRD-first filter)

`Corner/state_machines/duty_reinstate_lifts_a_suspension_when_a_verified_certificate_remains` — its setup requires filing a *second* live `GROUP_EX_CERT` for a holder who already has one VERIFIED, but PRD §3.2 states "A person may hold at most one live record per credential type; only records in `REJECTED` status are exempt", and the PRD names no error for a duplicate live filing. Every other route to a suspended holder who still has a VERIFIED required credential runs through credential acceptance, which §3.2 says reinstates automatically — so the manual endpoint's success path is unreachable from the PRD alone. Not weakened, not stubbed.

## Design-index defects found

- Corner stub `calculations/per_assignment_rounding_precedes_the_sum` cites `rounding_order_of_operations/labor_cost_rounds_per_assignment_then_sums`; the instance exists but under `rule_id: combinatorial_formula` — there is no `rounding_order_of_operations` rule. Instance name resolves, rule prefix is wrong.
- `validations/session_capacity_exceeded_at_the_offering_maximum` is internally unsatisfiable as written (offering cap 1 with `forecast_attendance: 3`, which PRD §3.5 rejects as a shape bound first); translated with a satisfiable forecast.
- `errors/contract_and_offering_state_guards_rejected` has one case expecting `ERR_INVALID_STATE_TRANSITION` for PAUSE-on-DRAFT where PRD §3.4 says `ERR_OFFERING_NOT_ACTIVE`; that single case was dropped, the instance stays covered.
- Several instances pre-compute timestamp literals without the three fractional digits PRD §2.4 mandates (`"...T00:00:00Z"`); those assertions were expressed as prefix comparisons rather than forcing a format the PRD forbids. Same treatment for yaml-asserted fields the PRD never declares (`Member.total_check_ins`, `ProgramSession.labor_cost_cents`, `review_note`, `badge_number` on the member row).

## Helper fixes applied after generation

- `fixtures.create_draft_contract(site_code=...)` raised `TypeError` (duplicate keyword) — now uses `setdefault`.
- `factories.incident_report_payload` defaulted `occurred_at_utc` to 09:00 on the clock's start date, which PRD §3.8 forbids as future-dated; default moved to `2026-07-31T16:05:00Z`.
- `constants.MALFORMED_ID`'s comment described the opposite of its value; corrected.
- Added `fixtures.read_participation_record` for parity with the other entity accessors.

Verification after the fixes: `pytest --collect-only` clean (182 items), `pyflakes` clean across all 24 files, and an AST pass confirms every `scenarios.*` / `api.*` / `ApiErrorId.*` reference and every `THRESHOLDS`/`TEST_DEFAULTS` key used by the suite resolves. No server was started and no broad process kill was ever issued.

## Step 6: Generate implementation — 2026-09-03T23:15:45.000Z

Implementation complete, smoke-tested end to end, and all smoke servers shut down by exact PID.

## Inventory — `workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `start.sh` | 11 | guarded `pip install` (skips when Flask present), `exec python3 app.py`, binds `0.0.0.0`, honors `PORT` (default 10000) |
| `requirements.txt` | 1 | `flask>=2.0` |
| `app.py` | 85 | `create_app()`, 10 blueprints, global request lock, `ApiError`/`HTTPException`/catch-all handlers, `app.json.sort_keys = False` |
| `core.py` | 615 | in-memory `Store`, envelope/meta builders, pagination, auth + scoping, ~30 field validators, clock |
| `calc.py` | 400 | the nine calculations (labor, readiness index, dual-variant attainment, incentive points, AED readiness, downtime credit, coverage penalty, dual-variant invoice, utilization rollup) |
| `cascades.py` | 336 | credential suspension, contract suspend/terminate, incident-equipment, offering pause, coverage/readiness refresh |
| `guards.py` | 37 | terminal-state sets, `terminal()`, `invalid_transition()`, `require_contract_active()` |
| `r_contracts.py` | 183 | contract lifecycle |
| `r_staff.py` | 157 | staff, credentials, drills |
| `r_facility.py` | 148 | rooms, assets |
| `r_programs.py` | 226 | offerings, sessions, status changes |
| `r_assign.py` | 120 | staff assignments |
| `r_members.py` | 301 | enrolment, eligibility, waivers, badges, participation, void |
| `r_incidents.py` | 125 | file/review/return/claim/close |
| `r_invoices.py` | 142 | draft/issue/dispute/rebill/pay |
| `r_ops.py` | 222 | clock, nightly readiness run, readiness summary, utilization report, attainment |
| `r_reads.py` | 325 | all 26 entity GETs with role lists, filters, scoping, health-note projection |
| **total** | **3434** | 70 URL rules = 40 POST + 29 endpoint-table GETs + `static` — exactly matches the PRD endpoint table |

No SQLite, no JSON on disk, no `/tmp` cache, no seeded rows; `__pycache__` removed.

## Smoke test (ports 18631 / 18632, killed by exact PID)

Full happy path verified: contract create → staff hire → credential file/verify (self-verification 403 `ERR_SELF_VERIFICATION_FORBIDDEN`) → drill (readiness 0 → 100) → submit → sponsor APPROVE → room + AED asset (`READY`) → offering ACTIVATE → session schedule → assignment create/confirm (session auto-advances to `STAFFED`) → member enrol → eligibility VERIFY → waiver + badge GRANT → session START → check-in (10 points) → COMPLETE → invoice draft/issue/dispute/rebill → participation void → incident file/review/return.

Calculations spot-checked against the PRD: lead labor `4700 x 70/60 = 5483`, support `5200 x 55/60 = 4767`, COST_PLUS base 33772 → 7% markup 2364 → gross 36136 → 1.5% volume credit 542 → net 35594; provisional attainment 15% vs final 3% (ROUND_HALF_UP on 2.5); `ytd_billed_cents` returns to 0 after dispute.

Negative/edge paths verified: `ERR_ROOM_TIME_CONFLICT` at a 0-minute gap but a clean 201 at exactly a 15-minute gap; `ERR_DUPLICATE_LEAD_ASSIGNMENT`; `ERR_CREDENTIAL_NOT_VERIFIED` for any role lacking the offering's credential; `ERR_STALE_MEMBER_VERSION` 412; `ERR_SESSION_START_TOO_EARLY`; `ERR_DUPLICATE_CHECK_IN`; `occurred_at_utc` in the future → 400; `ERR_SELF_REVIEW_FORBIDDEN`; limit 0/101 and offset -1 → 400 `ERR_INVALID_REQUEST`; unknown/absent role → 401 `ERR_UNAUTHENTICATED`; wrong role → 403 `ERR_UNAUTHORIZED`; unknown id → 404 `ERR_MEMBER_NOT_FOUND`; unknown route → 404 `ERR_INVALID_REQUEST`.

The SERIOUS + EQUIPMENT + asset_id cascade fired all four links correctly (asset `OUT_OF_SERVICE` with `out_of_service_since`, room `RESTRICTED` with `open_deficiency_count` 1, in-window session `CANCELLED_FACILITY`, assignments released) while leaving `uncovered_session_count` at 0 and accruing no penalty; `return` cleared the reviewer and bumped `return_count` without reversing the cascade.

Restart isolation confirmed: a fresh `bash start.sh` on a new port served empty lists (`total_count: 0`) and a new contract stamped `created_at`/`updated_at` = `2026-08-01T00:00:00.000Z`, `version: 1`, with PRD field order preserved. Health-note privacy confirmed: `health_metrics_note` is `null` for OperatorAdmin and readable for ComplianceAuditor.

**Orchestrator note:** Steps 5 and 6 were launched as background agents; Step 6 was launched one message after Step 5 rather than in the same message, but Step 5 had not yet created `test_suite/` at that instant, so the impl generator's physical isolation from the test suite held (and it was additionally forbidden by prompt from reading either test directory).

## Step 7: Run tests and iterate — 2026-09-03T23:47:34.241Z

Clean sweep: all 8 parallel rounds green at 182/182.

## Summary

**Iterations run:** 3 (iteration 1: 169/182 in all 8 rounds; iteration 2: 181/182; iteration 3: 182/182 in all 8 rounds). Failures were fully deterministic across rounds — no flakiness surfaced, and no load-induced timeouts.

**Tests deleted:** none. Two assertions were removed under STEP 1c partial-coverage handling (the enclosing tests were kept and still pass their PRD-covered assertions):
- `test_06…::test_badge_grant_for_a_waivered_but_unverified_member_rejected` — dropped `member.badge_number is None`. DEFAULT-VALUE / COMPUTED-FIELD SILENCE: PRD §3.6 mentions `badge_number` only as "an optional `badge_number` recorded alongside a grant"; it is never listed as a member response attribute (§3.6's enrolment field list and §4's "Fetch one member with both state dimensions and their incentive balance" both omit it) and no default is named. Scaffold rule: `Corner/errors/eligibility_not_verified_on_badge_grant_rejected`.
- `test_06…::test_badge_grant_after_eligibility_verification_accepted` — dropped `granted["badge_number"] == "B-1001"`, same silence, same scaffold rule.

**Fixes applied to `test_helpers/`:** none — the fixture layer was correct throughout.

**Fixes applied to `test_suite/`:**
- `test_12_cross_entity_state_and_scheduling.py` — 4 `validate_success(...)` calls on `POST /program-sessions` and `POST /staff-assignments` now pass `201`; both endpoints bring a new record into existence, so PRD §4 requires 201, and the default-200 validator was the bug.
- `test_05_endpoint_workflows.py` — `test_readiness_summary_flips_when_the_defibrillator_is_taken_out_of_service` asserted `201` on `POST /facility-assets/{id}/service-events`; changed to `200`. The suite was internally inconsistent here (test_11 asserted 200 for the same endpoint); §4 plus §2.6's closed list of aggregates (no service-event/inspection/drill entity anywhere in PRD) fixes 200 as the faithful reading.
- `test_10_lifecycle_paths_and_cascades.py` — `test_readiness_run_expiry_cascades_from_credential_to_uncovered_cancellations` asserted the vacated assignments end at `VACANT_NEEDS_COVER`. §3.5's NO_COVER branch states assignments in "`ASSIGNED`, `CONFIRMED`, **or** `VACANT_NEEDS_COVER` status move to `RELEASED`" and that "This is the branch the nightly sweep takes for at-risk sessions inside the lock window", so after step-one's link 4 fires the observable end state is `RELEASED`. Assertion re-pointed at `RELEASED` (still an exact-status check, not a weakening).

**Fixes applied to `implementation/`:**
- `r_facility.py::record_inspection` — `created(...)` → `ok(...)` (200). An inspection persists no record; it writes `last_inspection_on`/`last_cleanliness_score`/`open_deficiency_count` onto the room and may move `OPEN → RESTRICTED`, i.e. a lifecycle move per §4.
- `r_facility.py::record_service_event` — `created(...)` → `ok(...)` (200), same reasoning for the asset.
- `r_staff.py::record_drill` — `created(...)` → `ok(...)` (200); the drill updates the staff member's `last_drill_on` and `readiness_index` rather than creating an entity.

No implementation check was removed or weakened, no endpoint/field/side-effect was added, and storage remains in-memory only.

**Orchestrator verification:** all 8 `results.$i.json` present (written 23:43:03 UTC), each `passed == total == 182`, `failed == 0`.

## Step 8: Finalize PRD — 2026-09-03T23:56:23.000Z

Done. `PRD_FINALIZED.md` written with two edits.

**Size:** PRD.md 533 lines / 121,958 bytes → PRD_FINALIZED.md 533 lines / 122,459 bytes — line delta 0.0%, byte delta +0.41% (two paragraphs revised in place, no new sections).

**Changes**

- §3.6 (badge dimension) — revise — `badge_number` is now described as *accepted* on a `GRANT` (must be a non-empty string when supplied) but not persisted, and the member representation is stated to carry no badge-number field, so no response echoes it — `implementation/r_members.py:160` (validated by `opt_str`, never written into the member record at `r_members.py:76-88`).
- §4 (intro paragraph, before the endpoint table) — insert — one sentence pinning that the thirteen §2.6 aggregates are the only persisted records, so `POST /facility-rooms/{id}/inspections`, `POST /facility-assets/{id}/service-events`, and `POST /staff-members/{id}/drills` create nothing of their own and return the updated room / asset / staff member with HTTP 200 — `implementation/r_facility.py:65`, `implementation/r_facility.py:152`, `implementation/r_staff.py:56`.

**Per-edit pre-edit search log**

1. `badge_number` edit — (a) Subject: the `badge_number` payload field on badge-access grants and the member entity's field set. (b) Enumerated: `grep -rn badge_number implementation/` → single hit, `r_members.py:160` (`opt_str(..., 1, 80)`, result discarded); `r_members.py:50-89` (`new_record("member", …)` field list — no badge key); `r_members.py:153-173` (`badge_access` GRANT/REVOKE, only `access_status` mutated); `cascades.py:237-241` `revoke_badge` and `cascades.py:255-258` `terminate_member` (badge revocation cascades — no badge-number field touched); `core.py:318-330` `view()` (serializes every non-underscore key, so an absent key can never appear); `r_reads.py` member reads (same `view`); sweep step four in `r_ops.py` badge revocation. (c) Adjustment: avoided saying the value "is ignored" outright — impl still shape-validates it, so wording is "must be a non-empty string when supplied, but it is not persisted"; also avoided quoting the 1–80 length bound, leaving the upper bound under-determined rather than asserting a limit the PRD never states elsewhere for such fields.

2. §4 status-code edit — (a) Subject: which POSTs bring a record into existence (201) versus mutate an existing record (200), specifically inspections / service events / drills. (b) Enumerated: every `created(...)` callsite in `implementation/` (`grep -rn "created(" *.py` → exactly 15 calls across contract, amendment, room, asset, staff, credential, member, waiver, participation, offering, session, assignment, incident, invoice) and every `new_record("…")` kind (13 kinds — matches §2.6's list exactly, no inspection/service-event/drill collection); read `r_facility.py:41-65` (inspection writes `last_inspection_on`/`last_cleanliness_score`/`open_deficiency_count`, may move OPEN→RESTRICTED via `cascades.cancel_room_lock_window_sessions`, or RESTRICTED→OPEN with the `ERR_CONTRACT_NOT_ACTIVE` guard), `r_facility.py:113-152` (all four `event_type` branches mutate the asset and call `refresh_asset_readiness`), `r_staff.py:43-56` (drill sets `last_drill_on` + `refresh_readiness`); confirmed all remaining POSTs (`status-changes`, `verify`, `renew`, `duty-reinstate`, `submit`, `client-decision`, `service-status`, `confirm`, `release`, `badge-access`, `eligibility-decisions`, `void`, incident review/return/file-claim/close, invoice issue/dispute/rebill/pay, `daily-readiness-run`, `_clock/set_current_utc`) already return `ok(...)`/200. (c) Adjustment: scoped the new sentence to exactly those three endpoints and phrased the return value as "that updated record" rather than naming a body shape, so it stays consistent with all four service-event branches and both inspection outcomes; anchored it to §2.6's existing aggregate list instead of inventing a new rule about sub-resources generally.

No PRD edit was made for the two remaining Step 7 items: the `test_12` 201 corrections on `POST /program-sessions` / `POST /staff-assignments` (already determined by §4 — both create records, impl uses `created()`), and the `test_10` `RELEASED` re-point (already determined by §3.5's NO_COVER branch, which `cascades.cancel_session` implements by releasing `ASSIGNED`/`CONFIRMED`/`VACANT_NEEDS_COVER` assignments).

## Step 9: Complete PRD — 2026-09-04T00:26:30.000Z

Pass C complete. Final verification:

```
diff PRD_FINALIZED.md PRD_COMPLETED.md | wc -l  →  210   (files DIFFER; cmp confirms not identical)
lines:  PRD_FINALIZED.md 533   →  PRD_COMPLETED.md 537   (+4)
chars:  PRD_FINALIZED.md 122459 →  PRD_COMPLETED.md 146287  (+23,828)
headings identical, table-row count identical (no new sections, no new endpoint rows)
```

**Counts by pass** — Pass A 14 edits, Pass B 24 edits, Pass C 25 edits; **63 total** (34 ambiguity-pins, 29 mismatch-revisions). The 4 extra lines are two paragraphs inserted inside existing §2.4 and §2.11 during Pass A/B; everything else is in-paragraph. (Pass boundaries were flushed to disk, not git-committed — this task dir is untracked, and the repo commits task batches wholesale.)

### Pass C changes (25)

- §2.1 Roles — revise — mismatch — the scope-check list said "eight operations"; impl scope-checks ten writes (adds member enrolment and badge-access) plus a named set of single-record reads — `r_members.py:55,116,157`, `r_invoices.py:97,135`, `core.py:423`
- §2.1 Roles — revise — mismatch — pinned that list endpoints never reject on ownership but silently narrow (`_own_contract_only`), and that staff/credential/asset/assignment/incident reads are unscoped in both list and detail form — `r_reads.py:46,80,117,130,199,296`
- §2.3 Pagination — insert — ambiguity — equality filters are exact string comparisons, unknown values yield an empty page, an empty parameter is ignored, and the order is filters → ownership narrowing → limit/offset — `r_reads.py:16,278`
- §2.5 Logical Clock — insert — ambiguity — `current_utc` mandatory, response is that single normalised field, unparseable value is `ERR_INVALID_REQUEST`, backwards moves allowed — `r_ops.py:29`
- §2.10 Health data — revise — mismatch — PRD claimed a read by a non-permitted role returns `ERR_HEALTH_DATA_FORBIDDEN`; impl nulls the key and returns 200, so no read ever fails on health grounds — `r_reads.py:258`
- §2.11 rule 6 — revise — mismatch — rule 6 covered "write consent and read projection"; projection raises nothing, so only the write gate is ordered — `r_reads.py:264`
- §2.11 refinements — insert — mismatch — third refinement: on check-in the consent gate sits *between* rules 8 and 9 (note length 400 → consent 403 → member 404), and is skipped when the member does not resolve — `r_members.py:223,227,230`
- §2.11 refinements — insert — ambiguity — fourth refinement: a query-string identifier scopes before existence (readiness summary → 403) while a path identifier resolves first (utilization report → 404); a missing required query param outranks both — `r_ops.py:152,198`
- §3.8 Incidents — insert — ambiguity — a future `occurred_at_utc` is `ERR_INVALID_REQUEST`, checked before any identifier resolves — `r_incidents.py:34`
- §3.8 Incidents — insert — ambiguity — FK resolution order contract → staff → member → asset, all four resolved before containment, containment then tested staff → member → asset — `r_incidents.py:36-45`
- §3.8 Review — insert — ambiguity — `review_note` is length-validated but persisted nowhere — `r_incidents.py:72`
- §3.8 Return — insert — ambiguity — `return_note` is mandatory yet likewise discarded — `r_incidents.py:88`
- §3.9 Draft — insert — ambiguity — the version comparison precedes even the terminal check; only `TERMINATED`/`WITHDRAWN` are refused, so `DRAFT`/`PENDING_CLIENT_APPROVAL`/`SUSPENDED` contracts are drawable — `r_invoices.py:37-39`
- §3.9 Draft — insert — mismatch — the contract's `version` advances by **2** (explicit `version+1` write plus the mutation bump) and does so unconditionally, even with no prior draft to supersede — `r_invoices.py:64`, `core.py` `touch`/`upd`
- §3.9 Rebill — insert — ambiguity — only `issued_at` is cleared; `disputed_at` and `dispute_reason` survive the rebill — `r_invoices.py:120`
- §3.9 Pay — revise — mismatch — `payment_reference` is validated then discarded, never stored or returned — `r_invoices.py:137`
- §3.9 Sweep preamble — insert — ambiguity — `contract_id` comes from the body and must resolve (`ERR_CONTRACT_NOT_FOUND`) — `r_ops.py:48-49`
- §3.9 Sweep preamble — insert — ambiguity — the sweep has no contract-status precondition, terminal contracts included — `r_ops.py:44-49`
- §3.9 Step one — revise — mismatch — credential transitions are applied in full first, then the cascade runs once per affected holder in first-encountered order (deduplicated), not interleaved per expiry — `r_ops.py:58-80`
- §3.9 Step two — revise — mismatch — the 0-pin applies to anyone currently `SUSPENDED_FROM_DUTY`, not only those suspended tonight, and `OFFBOARDED` staff are recomputed by the ordinary formula — `cascades.py` `refresh_readiness`
- §3.9 Step three — revise — mismatch — `current_waiver_id` is cleared only when it pointed at the waiver that just expired — `r_ops.py:96-97`
- §3.9 Step five — revise — mismatch — PRD used a nonexistent `next_maintenance_due_on`; impl flags only non-AED `IN_SERVICE` assets on the `service_interval_days` rule and never moves an AED to `MAINTENANCE_DUE` — `r_ops.py:110-124`
- §3.9 Tally — revise — mismatch — "every count is a transition count" is false: `aed_not_ready` is a standing count and `penalty_accrued_cents` a floored before/after difference; also pinned which steps feed the other counters — `r_ops.py:124,138,142`, `cascades.py:182-206`
- §3.9 Readiness summary — insert — ambiguity — required `contract_id` query param, recomputes nothing, and every figure is a standing count (credential counts span all types; `sessions_at_risk` ignores the lock window; `rooms_restricted` excludes `CLOSED`; `assets_out_of_service` spans all types and double-counts an out-of-service AED) — `r_ops.py:149-192`
- §3.9 Utilization report — insert — ambiguity — required `period_month` query param validated as `YYYY-MM` (`ERR_INVALID_REQUEST`), unbounded relative to term/today, only the contract's own members counted, and no `contract_id` in the payload — `r_ops.py:200-203`, `calc.py` `utilization_rollup`
- §3.7 Participation — insert — ambiguity — both check-in window edges inclusive and independently optional, unparseable bound is `ERR_INVALID_REQUEST`, same rules for the session listing's `starts_after`/`starts_before` — `r_reads.py:26-43`

**Two PRD self-contradictions resolved in the implementation's favour during Pass C:** §2.10's "always receive `health_metrics_note` as null" versus its `ERR_HEALTH_DATA_FORBIDDEN` read claim (impl nulls, never raises), and §3.9 step five's `next_maintenance_due_on` versus §3.3's `service_interval_days` rule (impl uses the interval).

**Orchestrator verification:** PRD_COMPLETED.md is 537 lines, differs from PRD_FINALIZED.md by 210 diff lines, ends at a real boundary (final error-table row), retains exactly the 5 top-level sections, and every `implementation/*.py` mtime predates Step 8 — Steps 8 and 9 touched no code.

## Pipeline complete — 2026-09-04T00:27:00.000Z

All nine steps done. Final state: 182/182 tests passing in all 8 parallel sweep rounds; `workspace/PRD_COMPLETED.md` written.
