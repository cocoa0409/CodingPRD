# Worklog — task_2747_appraisal_review_reconsideration_of_value

## Step 1: Create task directory — 2026-09-04T15:35:40.200Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2747_appraisal_review_reconsideration_of_value` and its `workspace/` subdirectory. Index 2747 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no index was allocated locally (other pipelines run concurrently on this host).

## Step 2: Generate Scaffold — 2026-09-04T17:38:55.275Z

All three artifacts are complete and the lint is clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    52
  §1.1 entities declared:     15
  §1.8 instances scanned:     19
  §1.9 instances scanned:     66
  Calls scanned (§1.8+§1.9):  1125

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files

- `SCAFFOLD.yaml` — 3,635 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2,270 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — 5,120 lines

Generated purely from the scenario text plus the scaffold-generator spec; no sibling task directory was listed, globbed, grepped, or read.

## §1.0–§1.7 counts

`api_prefix: /appraisal-desk`; profile = `compliance_audit` / `multi_party_negotiation`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers]`, topology `graph`, SM shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`, difficulty `beyond_expert`.

- 15 entities (LoanFile, Appraiser, AMC, PanelMembership, Appraisal, ComparableSale, RuleCheckResult*, BiasIndicatorFlag, AppraiserCommunication*, DeskReview, EscalationOrder, ROVRequest, ROVEvidenceItem, DisputeCase, ValueRevision* — starred = `common_fields: false`)
- 11 state-machine dimensions, 3 §1.2.1 OCC rules, 12 calculations, 42 ordered validations, 52 endpoints, 48 error codes, 7 roles

## §1.8 — 19 instances / 9 rules

dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

## §1.9 — 84 instances (66 with recipes, 18 `excluded_because` stubs)

entities 12, state_machines 14 (4 stubs), calculations 14 (5 stubs), validations 8, endpoints 4, rbac 5, cross_cutting_complexity_layers 7 (2 stubs), errors 19 (7 stubs), consistency_model 1.

All 48 error codes are triggerable across §1.8+§1.9; names are unique across both design files; no forbidden concurrency vocabulary in any file.

## Design adjudications

1. **Two revert edges added to SCAFFOLD.yaml** — Appraisal `ESCALATED → IN_DESK_REVIEW` and DeskReview `ESCALATED → SUBMITTED`, both fired by `escalation-orders/{id}/cancel`, because the endpoint declared reopening side effects no machine allowed; §1.8 instance 18 (`escalation_spend_ledger_restored_on_order_cancel`) was rewritten to assert the reopen instead of the opposite.
2. **AMC breach constants pinned** — `AMC_PROBATION_BREACH_COUNT 2` / `AMC_SUSPENSION_BREACH_COUNT 4` were referenced by the AMC `panel_status` cascade but defined nowhere; added as transition `note:`s and exercised by the §1.9 endpoints instance (one breach leaves the AMC ACTIVE).
3. **§1.9 tiered_pricing redesigned** to the SECOND_APPRAISAL top-tier straddle (65000 + 19500 rush = 84500 > TIER2_CEIL 80000 → 1000 bps → 76050) so it does not duplicate §1.8's FIELD_REVIEW rush case.
4. **weighted_scoring rounding case recomputed** (8 sections / 2 closed comps / 2 exhibits → 10000/6667/2857 → `round_half_up(7571.5) = 7572` vs the forbidden 7571) after the first candidate failed to diverge.
5. **Bias threshold 25 reached via the comparable channel** (4 comps, 2 off-band → comp_skew 5000 → index 25) since narrative hits arrive in steps of 12; paired with an exactly-24 case.
6. **Budget boundary** uses `escalation_budget_cents = 45000` so the first FIELD_REVIEW lands exactly ON the ceiling and is accepted, the second gets the 402 — with the second inspection window deliberately outside the 90-minute travel buffer so priority 31 cannot be the cause.
7. **Panel cascade boundary** built from revision counts (1 of 2 → rate 5000 → score exactly 7000, stays ACTIVE under strict `<`; 2 of 2 → 4000 → SUSPENDED, never auto-REMOVED at REMOVAL_THRESHOLD 4000).
8. **Revision cap** asserted on both sides of the inclusive bound: 49000000 = 2250 bps rejected, 48000000 = exactly 2000 bps accepted.
9. Two lint/field-name corrections during verification: `rule_check_fail_count` (not `rule_fail_count`) and `variance_vs_reported_bps` (not `value_variance_bps`); one "simultaneously" reworded out of a §1.9 distinguishing_aspect.

## Step 3: Copy Shared Files — 2026-09-04T17:39:17.646Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T17:59:51.591Z

PRD complete and verified.

**Artifact:** `workspace/PRD.md` — **459 lines / 118,600 bytes**, built with 12 chunked appends plus targeted repairs (no truncation).

**Section list**
- `# Lender Appraisal Review Desk API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` → 2.1 Desk Participants and Role-Based Access Control · 2.2 API Response Structure (fixed block, verified byte-identical to `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Resource Identity, Timestamps and the Logical Desk Clock · 2.5 Money, Basis Points and Rounding Discipline · 2.6 Stale-Read Protection on Parent Resources · 2.7 Left-to-Right Path Resolution and Referential Ordering · 2.8 The Validation Ladder · 2.9 Two-Dimensional Status Modelling and Cascade Discipline · 2.10 Appraiser Independence and the Non-Influence Principle
- `## 3. Business Logic & Workflows` → 3.1 Loan File Intake and the Underwriting Dimension · 3.2 The Appraiser Panel · 3.3 Report Delivery, the Comparable Grid and Supersession · 3.4 The Automated Receipt Rule-Check Battery · 3.5 Bias Screening, Quarantine, and the Appraiser-Communication Channel · 3.6 Desk Review: Quality Scoring, Submission and the Escalation Decision · 3.7 Escalation Orders: Assignment, Pricing, Delivery and Reversal · 3.8 Reconsideration of Value · 3.9 Disputes, the Value of Record, and Panel Performance Consequences
- `## 4. Endpoint Definitions`
- `## 5. Error Code Catalogue`

**Coverage (all machine-verified against SCAFFOLD.yaml)**
- 52 endpoints — §4 table has 54 rows (header + separator + 52) and exactly 4 columns.
- 48 error codes — §5 table has 50 rows and exactly 2 columns; every one of the 48 IDs is also named in the prose body.
- 12 calculations — all documented, including both dual-variant pairs (`PRELIMINARY`/`FINAL` quality score, `ROLLING_12M`/`LIFETIME` performance score); every numeric constant appears literally.
- 42 validations — §2.8 enumerates priorities 1–42 in order; automated check confirms each numbered item names the scaffold's error ID at that priority (the only two "mismatches" are the deliberate `ERR_<RESOURCE>_NOT_FOUND` placeholders, expanded into the 10 concrete 404 codes in §2.7).
- 11 state machines / 86 transitions — 84 rendered as explicit `FROM → TO` edges; the remaining two are the dynamic-target `QUARANTINED → quarantine_return_status` (both concrete restores spelled out) and it plus `SUBSTANTIATED → CLEARED`, both now explicit in prose.

**Hard contracts:** Contract 1 field-name coverage **PASS** (167/167 identifiers backticked); Contract 2 rule coverage **PASS** (OCC rules, cascades, side effects, defaults/initial values and sibling symmetry all present); Contract 3 §3 path purity **PASS** (no `/`-prefixed token, bare method, or method+path anywhere in §3, backticked or raw).

**Repairs made during verification:** corrected `ERR_PANEL_ACTION_NOT_PERMITTED` from HTTP 409 to 422; added `rov_request_id` path-stamping sentence in §3.8; added explicit arrows for the rule-check re-run edges, escalation assign/cancel edges, dispute resolution edges, bias-flag edges, and the three explicit underwriting edges; documented the re-assignment ledger *replacement* (versus the first assignment's addition) and the `open_assignment_count` hand-off; made the completeness weights numerically explicit (0.50 / 0.30 / 0.20).

**Final heading:** `## 5. Error Code Catalogue`
**Final line:** `` | `ERR_ESCALATION_BUDGET_EXCEEDED` | 402 | ``

Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling task directory was accessed.

**Orchestrator truncation check:** independently verified — `wc -l -c` = 459 lines / 118,600 bytes; tail ends on the final complete row of the §5 error table (`ERR_ESCALATION_BUDGET_EXCEEDED | 402 |`), a real section boundary, not mid-sentence. No regeneration needed.

## Step 5: Generate Unit Tests — 2026-09-04T19:49:08.963Z

Test suite generation for task 2747 is complete.

## Deliverables (both at the task root, nothing written under `workspace/`)

`test_helpers/` — 9 files, 3001 lines: `constants.py` 161, `types.py` 543, `api_errors.py` 142, `test_users.py` 97, `api_client.py` 248, `factories.py` 329, `assertions.py` 602, `fixtures.py` 710, `__init__.py` 169.

`test_suite/` — `conftest.py` (49) plus 18 test modules, 8943 lines, **163 tests**, all collected by pytest with no import errors and no `skip`/`skipif`/`xfail` anywhere:

| file | lines | tests |
|---|---|---|
| test_01_dual_variant_calculations.py | 315 | 5 |
| test_02_combinatorial_formulas.py | 390 | 7 |
| test_03_non_linear_state_machines.py | 246 | 4 |
| test_04_transitive_cascades.py | 362 | 4 |
| test_05_validation_priority_conflicts.py | 273 | 4 |
| test_06_boundary_precision.py | 276 | 6 |
| test_07_cross_entity_state_dependency.py | 266 | 5 |
| test_08_resource_temporal_overlap.py | 335 | 6 |
| test_09_compensating_invariants.py | 369 | 7 |
| test_10_entities.py | 659 | 13 |
| test_11_state_machines.py | 802 | 13 |
| test_12_calculations.py | 938 | 16 |
| test_13_validations.py | 708 | 14 |
| test_14_endpoint_behaviour.py | 520 | 10 |
| test_15_role_authority.py | 607 | 11 |
| test_16_cross_cutting_layers.py | 605 | 12 |
| test_17_error_catalogue.py | 1025 | 23 |
| test_18_consistency.py | 200 | 3 |

## Coverage audit

An AST checker over every test verified: exactly one `Design:` line per test, as the last non-empty docstring line; every tag resolves to a real non-stub instance; every `PRD: "..."` block is a whitespace-normalized literal substring of `workspace/PRD.md`. Final run: **163 tests tagged, 84 distinct instances, 0 failures.**

- Queue A (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`): **19/19 instances** covered, 48 tests.
- Queue B (`SCAFFOLD_CORNER_DESIGN.yaml`): 84 instances = 66 live + 18 stubs. **65/66 live instances** covered, 115 tests — entities 12, state_machines 10, calculations 9, validations 8, endpoints 4, rbac 5, cross_cutting_complexity_layers 5, errors 11, consistency_model 1.

Skips, all with reasons:

1. **18 stub instances** (state_machines 4, calculations 5, cross_cutting 2, errors 7) carry no scripted steps — they cross-reference difficulty instances already covered by queue A.
2. **`errors/error_bias_quarantine_active_blocks_the_loan_decision_rejected`** — skipped as not uniquely derivable. Its trigger asks for `target_status: "SUSPENDED"`, which the PRD does not declare as an explicit underwriting transition, so the `ERR_INVALID_STATE` (409) rung fires ahead of `ERR_BIAS_QUARANTINE_ACTIVE` (422); and the freeze is worded against "a loan whose value-of-record appraisal is under a substantiated bias quarantine" while the scripted loan's `value_of_record_appraisal_id` is null. Every in-spec repair path either contradicts the ACCEPT preconditions, destroys the only declared `INDICATED → SUBSTANTIATED` edge, or rewrites the instance's own asserted figures, so the gap was left as a gap.

## Design-index defects worked around without weakening the PRD

- `tier: "REVIEW"` appears in several corner instances but is not in the PRD enum — used `REVIEW_SPECIALIST`.
- `error_communication_locked_on_a_superseded_appraisal_rejected` scripts a supersession of a `RECEIVED` appraisal, which the PRD refuses (`review_status` must be `RETURNED_TO_AMC`); the setup was rebuilt through desk review → `RETURN` → superseding delivery with the asserted outcome unchanged.
- Non-PRD fields never asserted (`comp_age_days`, ROV `intake_note` at birth, `collateral_status == VALUE_CONTESTED` on a pre-appraisal loan); all-zeros UUIDs replaced with v4-shaped literals; timestamps compared through `assert_instant` rather than raw `==`.

Note: `workspace/implementation/` was already present and populated by another agent; I neither read nor wrote anything inside it.

## Step 6: Generate Implementation — 2026-09-04T19:49:08.963Z

Implementation complete and verified.

## Modules (24 files, 3,169 lines of Python)

`workspace/implementation/`

| file | lines | file | lines |
|---|---|---|---|
| `start.sh` (exec, guarded pip) | 8 | `services/constants.py` | 141 |
| `requirements.txt` | 1 | `services/loans.py` | 97 |
| `app.py` | 63 | `services/panel.py` | 149 |
| `db.py` | 99 | `services/appraisal.py` | 180 |
| `errors.py` | 73 | `services/bias.py` | 66 |
| `response.py` | 130 | `services/review.py` | 75 |
| `middleware.py` | 60 | `services/escalation.py` | 71 |
| `validate.py` | 217 | `services/revision.py` | 52 |
| `routes/common.py` | 86 | `services/evidence.py` | 33 |
| `routes/reference.py` | 339 | `routes/escalation_orders.py` | 195 |
| `routes/appraisals.py` | 393 | `routes/rov.py` | 278 |
| `routes/desk_reviews.py` | 180 | `routes/disputes.py` | 192 |

**52 endpoints** implemented — exactly matching the SCAFFOLD endpoint table (extracted programmatically, not from memory), including the `_clock/set_current_utc` control endpoint.

## Verification
- Every `.py` compiles (`py_compile` loop, `ALL_COMPILE_OK`); `__pycache__` cleaned from the implementation tree.
- In-memory only: 15 empty dicts in `db.py`, no SQLite, no file I/O, no seeding — grep for `seed|preload|sqlite|open(` matches only doc comments.
- Two live boots on `PORT=39747` + **101 smoke assertions across two suites, 0 failures**: envelope/meta/request-id/timestamp formats, auth/RBAC/pagination/OCC errors, all 5 OCC endpoints, the 8-row rule battery with exact numerics (completeness 8571 = 0.50·sections + 0.30·comps + 0.20·(2/7); indicated value 49466667 via per-comp rounding; variance 107 bps), bias index 69 with `TERM_1/TERM_2/TERM_7/COMP_BAND_SKEW` in declared order, desk-review open→submit→decide with SoD and the escalation matrix, escalation pricing (SECOND_APPRAISAL 65000 → 500 bps → 61750), the 90-min buffered half-open window conflict *and* its exact boundary acceptance, closed unbuffered dispute-slot capacity, ROV evidence admissibility ladder + round limit, dispute default/overturn with the compensating revision and AMC breach cascade, and the full 6-way quarantine cascade with the appeal restore. Server killed by exact PID (`lsof -ti tcp:39747`); port confirmed free.

## Two PRD ambiguities resolved this pass (both produced code changes)

1. **Which review states can be quarantined.** §3.5 says "Quarantine is reachable from **every** non-terminal review state" but then enumerates only five edges, and SCAFFOLD declares those same five with a note repeating "the same transition exists from every non-terminal review_status". I had implemented the five-state whitelist, which wrongly rejected substantiation on an `ESCALATED` appraisal. **Chosen interpretation:** the prose and the `quarantine_return_status` constraint ("any review_status other than QUARANTINED or SUPERSEDED, or null") are authoritative — substantiate is allowed from every review status except `SUPERSEDED` (the only terminal one), and the only declared precondition remains `flag.status == OPEN`. When the appraisal is already `QUARANTINED` (a second OPEN flag — an anticipated case, since the appeal edge has a "no other flag is SUBSTANTIATED" guard), the snapshot is **not** overwritten, keeping the field within its stated constraint.

2. **Whether the loan is pulled into quarantine unconditionally.** §3.5's lead sentence says `collateral_status` "is set to QUARANTINED" flatly, but the same sentence's tail and §3.9 both restrict it: "on the collateral dimension both `VALUE_ACCEPTED → QUARANTINED` and `VALUE_REVISED → QUARANTINED` follow" / "pulls the loan into quarantine **from either resting state**". **Chosen interpretation:** the twice-stated restriction wins — the loan moves to `QUARANTINED` only from those two resting states, so quarantining an appraisal that is not yet the value of record leaves the loan at `UNDER_REVIEW`. This is consistent with §2's framing of `collateral_status` as a projection of the *value-of-record* appraisal and with §3.2's `ERR_BIAS_QUARANTINE_ACTIVE` condition ("a loan whose **value-of-record** appraisal is under a substantiated bias quarantine").

(Earlier resolved ambiguities, unchanged: `ERR_INVALID_WINDOW` vs `ERR_INVALID_REQUEST` — both window bounds absent is a body-shape error, exactly-one-present or reversed is `ERR_INVALID_WINDOW`, per "both are present when either is"; and derived counters are recomputed from the store rather than incremented, verified equivalent to the PRD's increment narrative at every trigger.)

**Orchestrator note:** Steps 5 and 6 were launched concurrently in a single message, so the implementation generator started before `test_suite/` existed and could not read it. Verified post-hoc that `test_helpers/` and `test_suite/` sit at the task root (not under `workspace/`) and that no stray worklog.md was written anywhere else in the tree.

## Step 7: Run Tests and Iterate — 2026-09-04T20:10:50.741Z

Clean. `worklog.md` untouched (mtime still 19:49, before I started), no stray test dirs under `workspace/`.

## Summary

**Iterations run:** 2. Iteration 1 → 159/163 in all 8 rounds (4 deterministic failures, identical set every round — no flakiness anywhere in the suite). Iteration 2 → **163/163 in all 8 parallel rounds**.

**Tests deleted:** none. All four failures survived STEP 1 coverage + unique-derivability.

**Fixes applied to `test_suite/`** (2 assertions, both PRD-silent per STEP 1c partial-coverage handling — the surrounding assertions were PRD-verbatim, so only the uncovered line was replaced, not the test):
- `test_suite/test_17_error_catalogue.py:97` — `test_a_request_carrying_no_identity_headers_is_unauthenticated` asserted `refused.json()["success"] is False`. PRD §2.2 enumerates the error envelope exhaustively as `meta` / `response_type` / `data`, and `grep -n success workspace/PRD.md` returns no envelope field anywhere in 460 lines. A faithful implementer would never emit `success`. Replaced with `response_type == "error"`, which *is* PRD-verbatim from the §2.2 error envelope — a strictly more faithful assertion, not a weaker one.
- `test_suite/test_17_error_catalogue.py:181` — `test_every_path_addressable_type_reports_its_own_not_found_code`, same `["success"]` probe inside the 7-way not-found loop, same replacement. The exact `error_id` and 404 assertions for all seven path-addressable types were left fully intact.

**Fixes applied to `test_helpers/`:** none — no fixture, factory, or role-header bug was implicated.

**Fixes applied to `implementation/`** (2 genuine PRD-fidelity defects):
- `routes/common.py` `active_membership()` + `routes/reference.py` `create_membership()` — the panel-enrolment duplicate check keyed on appraiser+company only, so a second enrolment on a *different* coverage state was wrongly refused `ERR_DUPLICATE_PANEL_MEMBERSHIP`. PRD §3.2: "At most one active membership may exist for any one combination of appraiser, company, **and coverage state**" (§2.8 rung 36 agrees). Added an optional `coverage_state` narrowing argument and passed it at enrolment. Deliberately left unset at the two eligibility gates (delivery `routes/appraisals.py:65`, escalation assignment `routes/escalation_orders.py:63`), which PRD scopes to the appraiser/company pair only — a state-narrowed check there would have been a new, wrong restriction.
- `services/appraisal.py` + `routes/appraisals.py` `add_comparable()` — adding a comparable called `refresh_grid_rollups()`, which also wrote `max_gross_adjustment_bps` / `max_net_adjustment_bps`. PRD §3.3 states these "start at 0" on delivery and enumerates exactly what comparable addition refreshes ("`eligible_comp_count` ... and its `closed_comp_count`" — the maxima are absent from that list), while §3.4 assigns the maxima to the rule-check run ("the run ... writes `max_gross_adjustment_bps`, `max_net_adjustment_bps`"). Split out `refresh_comp_counts()` for the counts-only path; `refresh_grid_rollups()` now delegates to it and adds the maxima, and remains the run's entry point. I audited all 12 maxima assertions across the suite first — every non-zero one reads after a rule-check run, so the narrowing was safe.

Both implementation fixes tightened fidelity to PRD prose; no PRD-required check was removed or weakened, no endpoint/field/capability was added, and storage remains in-memory Python dicts with nothing seeded at startup.

**Orchestrator verification:** independently re-read all 8 `results.$i.json` (all written 20:05): every round `passed=163 total=163 failed=0`. Step 7 is genuinely clean, and because it applied 2 `implementation/` fixes, Step 8 is NOT skipped.

## Step 8: Finalize PRD — 2026-09-04T20:14:37.599Z

Both PRD edits applied; `PRD_FINALIZED.md` created at `workspace/PRD_FINALIZED.md`.

## Line counts
- `PRD.md`: 459 lines / 118,600 bytes
- `PRD_FINALIZED.md`: 459 lines / 119,074 bytes
- Line delta: 0 (+0.00%); byte delta +474 (+0.40%). Both edits are in-paragraph insert/revise, no new sections.

## Changes
- **§3.2 (panel memberships)** — revise — "An active membership becomes `SUPERSEDED` in exactly **two** circumstances: when a later membership legitimately replaces it for the same appraiser, company, and coverage state, and when the appraiser is removed…" → "in exactly **one** circumstance: when the appraiser is removed… Enrolment itself never supersedes an earlier membership, since a second enrolment on the same triple is refused outright rather than allowed to replace its predecessor." — `routes/reference.py:309-310` (refusal) and `routes/reference.py:240-243` (the sole supersession path).
- **§3.3 (comparable grid)** — insert — appended one sentence pinning that a comparable addition refreshes only `eligible_comp_count`/`closed_comp_count`, that `max_gross_adjustment_bps`/`max_net_adjustment_bps` are written by the §3.4 rule-check run and by nothing else (so they read 0 on a filled-but-unscored grid and otherwise hold the last run's values) — `services/appraisal.py:24-44`, `routes/appraisals.py:178`.

No edit for the two `test_suite/test_17_error_catalogue.py` `["success"]` fixes: §2.2 already enumerates the success/error envelopes exhaustively (`meta` / `response_type` / `data`), and `implementation/response.py` emits exactly that, with no `success` key anywhere — PRD already uniquely determines it.

## Per-edit pre-edit search log

**Edit 1 — §3.2 membership supersession**
- (a) Subject: what causes a `panel_memberships` row to leave `ACTIVE` for `SUPERSEDED`, and what a repeat enrolment does.
- (b) Enumerated: `grep -rn "SUPERSEDED"` across all impl `.py` — only writer of membership status is `routes/reference.py:240-243` (`REMOVE` panel action); read `routes/reference.py` `create_membership()` (refuses via `ERR_DUPLICATE_PANEL_MEMBERSHIP`, never mutates an existing row), `routes/common.py:80-95` `active_membership()` (all three callsites: `reference.py:309` state-narrowed, `appraisals.py:65` delivery pair-only, `escalation_orders.py:63` assignment pair-only), `services/panel.py` (`apply_appraiser_cascade` never reaches `REMOVED` and never touches memberships; `refresh_appraiser_counters` only counts `ACTIVE` rows), `services/constants.py:17` (`MEMBERSHIP_STATUSES` = ACTIVE/SUPERSEDED only). Also cross-checked §3.9's `REMOVE` prose and `test_suite/test_10_entities.py:609` / `test_17_error_catalogue.py:900` which both assert non-superseding behavior.
- (c) Adjustment: kept the removal clause verbatim rather than rewriting it, and phrased the new clause about *enrolment* only (not "no other operation"), so the §3.9 `REMOVE` cascade and the pair-only eligibility gates in §3.3/§3.7 remain untouched and un-narrowed.

**Edit 2 — §3.3 comparable-addition roll-ups**
- (a) Subject: which appraisal-level roll-ups a comparable addition writes, and who owns the adjustment maxima.
- (b) Enumerated: `grep -rn "max_gross_adjustment_bps\|max_net_adjustment_bps\|eligible_comp_count\|closed_comp_count"` across impl — writers are `routes/appraisals.py:84-87` (delivery, all 0), `services/appraisal.py:33-34` (`refresh_comp_counts`, counts only), `services/appraisal.py:42-43` (`refresh_grid_rollups`, maxima), called only from `run_rule_checks` (`services/appraisal.py:95`); readers are the rule battery positions 1/2/5/6 (`services/appraisal.py:61,116,137,147`), the comp-limit guard (`routes/appraisals.py:158`) and desk-review clause three (`services/review.py:66`). Confirmed the bias screen (`services/bias.py` via `routes/appraisals.py:233`) and desk-review open do not refresh either field.
- (c) Adjustment: replaced an initial "stay at 0 until the run" phrasing with "written by the rule-check run of §3.4 and by nothing else… and after a run they keep the values that run wrote until the battery is run again", because a grid unlocked by `RETURN` can take new comparables *after* a run — the stricter "0" wording would have mis-described that off-Step-7 path. Left §3.4's own "the run … writes `max_gross_adjustment_bps`, `max_net_adjustment_bps`" and §3.3's read-payload sentence verbatim.

**Orchestrator verification:** `cmp` confirms `PRD_FINALIZED.md` DIFFERS from `PRD.md` (459 lines / 119,074 bytes vs 459 / 118,600).

## Step 9: Complete PRD — 2026-09-04T20:46:06.350Z

Run as **three sequential module-partitioned passes** over one shared `PRD_COMPLETED.md` (pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden to copy, and each verified the earlier passes' edited lines were still intact). Partition: pass 1 = envelope/meta/pagination/auth/RBAC plumbing + validation-ladder machinery + reference data (`app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `validate.py`, `routes/common.py`, `routes/reference.py`, `services/constants.py`, `services/loans.py`, `services/panel.py`); pass 2 = appraisal delivery/supersession, comparable grid, rule-check battery, bias screening/quarantine, communication channel, desk review (`routes/appraisals.py`, `services/appraisal.py`, `services/bias.py`, `routes/desk_reviews.py`, `services/review.py`); pass 3 = escalation orders, ROV + evidence, disputes, value revisions (`routes/escalation_orders.py`, `services/escalation.py`, `routes/rov.py`, `services/evidence.py`, `routes/disputes.py`, `services/revision.py`).

### Pass 1 — 22 edits (17 ambiguity-pins, 5 mismatch-revisions); 119,074 → 126,204 chars

- §2.1 — revise — ambiguity — a header holding only whitespace counts as empty for `ERR_UNAUTHENTICATED` — `middleware.py:40-43`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars; `api_request_timestamp` reads the logical clock, not wall time — `response.py:24,42,46`
- §2.3 — revise — mismatch — created_at ties break by **insertion order** (PRD previously said "remains created_at ascending", i.e. no tiebreak) — `db.py:90-95`
- §2.3 — insert — ambiguity — list filters are exact raw-string matches applied before the window; a non-matching value yields an empty page with `total_count` 0; error responses also omit the four pagination keys — `routes/common.py:72-77`, `response.py:81-84`
- §2.4 — insert — ambiguity — the clock endpoint answers HTTP 200 with an empty `data` object — `routes/reference.py:22-27`, `response.py:77`
- §2.7 — insert — ambiguity — an absent or non-string body FK is a shape failure (400), not a dangling reference; a later dangling FK still wins with its 404 — `routes/common.py:58-69`
- §2.8 rung 8 — insert — ambiguity — integer fields must be JSON integers (bool/float/numeric-string malformed); decimals accept number or numeric string; `+00:00` accepted as `Z`; non-object body malformed vs. absent body read as `{}`; uniqueness checks sit on this rung with the same code — `validate.py:30-38,80-84,114-132,159-171`
- §2.8 note — insert — mismatch — documented the one ladder departure: on the underwriting-status move, quarantine (rung 21) is evaluated ahead of transition-existence (rung 11) — `routes/reference.py:99-119`
- §2.9 — insert — ambiguity — counter refreshes/score recomputes and the automatic cascades they trigger bump `updated_at` only, never `version`; on loan files a new `collateral_status` does bump `version` while a pure value recompute does not — `services/panel.py:28,82,124`, `services/loans.py:47,59-63`, `routes/desk_reviews.py:63`
- §3.1 — insert — ambiguity — duplicate `loan_number` → `ERR_INVALID_REQUEST` (400) — `routes/reference.py:48-50`
- §3.1 — insert — ambiguity — loan withdrawal cancels pending orders with `cancel_reason` null and applies the same revert edges (review→SUBMITTED, appraisal→IN_DESK_REVIEW) — `routes/reference.py:129-146`
- §3.1 — revise — mismatch — quarantine gate also fires on `collateral_status == QUARANTINED`, and fires before transition lookup — `services/loans.py:72-78`, `routes/reference.py:99`
- §3.2 — insert — ambiguity — duplicate `license_number` → `ERR_INVALID_REQUEST` — `routes/reference.py:158-160`
- §3.2 — insert — ambiguity — `open_assignment_count`/`completed_assignment_count`/`panel_membership_count` are derived and recomputed; appraiser listing filters `panel_status`, `license_state` — `services/panel.py:12-28`, `routes/reference.py:195-196`
- §3.2 — insert — ambiguity — duplicate AMC `name` → `ERR_INVALID_REQUEST` — `routes/reference.py:261-263`
- §3.2 — insert — ambiguity — `ytd_escalation_spend_cents` = sum of `total_cost_cents` over ASSIGNED/REASSIGNMENT_REQUIRED/COMPLETED orders, `open_dispute_count` = OPEN disputes, both derived; AMC listing filters `panel_status` — `services/panel.py:108-136`, `routes/reference.py:290`
- §3.9 — insert — ambiguity — `ltv_bps`/`decision_impact` null when effective value ≤ 0; recompute is a no-op with no value-of-record — `services/loans.py:35-46`
- §3.9 — revise — mismatch — the recompute-and-cascade sequence runs at **four** moments, not five; a bias-quarantine lift does not recompute loan values — `services/loans.py:31`, callers in `routes/desk_reviews.py:148`, `routes/rov.py:223`, `services/revision.py:49` vs. `routes/appraisals.py:376-380`
- §3.9 — insert — ambiguity — full collateral projection map used when a quarantine is lifted (VALUE_CONTESTED, UNDER_REVIEW group, PENDING_APPRAISAL fallback) — `services/loans.py:87-97`
- §3.9 — insert — ambiguity — the automatic cascade never improves standing, and a direct move to SUSPENDED leaves `probation_started_at` untouched — `services/panel.py:68-84`
- §3.9 — revise — mismatch — `MONITOR` is a self-transition only when the recomputed score supports current standing; otherwise the MONITOR itself performs the degrade edges and releases second-appraisal orders — `routes/reference.py:214-217`, `services/panel.py:52-65`
- §3.9 — insert — ambiguity — REINSTATE/REMOVE read the stored `performance_score_bps` without recomputing; a missing/empty `removal_reason` → `ERR_PANEL_ACTION_NOT_PERMITTED`; version check follows body-shape checks — `routes/reference.py:205-237`

Cross-checks (read-only, off-partition): `routes/appraisals.py`, `routes/desk_reviews.py`, `routes/escalation_orders.py`, `routes/rov.py`, `routes/disputes.py`, `services/revision.py`; also verified `errors.py` is an exact set/status match with the §5 table (no drift).

### Pass 2 — 30 pins via 21 Edit calls over 19 lines (21 ambiguity-pins, 9 mismatch-revisions); 126,204 → 131,955 chars

- §3.3 — revise — mismatch — rung-4 ownership on delivery runs only when `amc_id` is a non-empty string; absent/non-string → `ERR_INVALID_REQUEST`, `""` → `ERR_AMC_NOT_FOUND` — `routes/appraisals.py:32-38`
- §3.3 — insert — ambiguity — future `effective_date` → `ERR_INVALID_REQUEST` (400) on the body-shape rung, ahead of the version token — `routes/appraisals.py:53`
- §3.3 — insert — ambiguity — `narrative_text` required but may be empty; `sections_present` may be an empty array — `routes/appraisals.py:48,50`
- §3.3 — revise — mismatch — `total_appraisal_count` is a recomputed roll-up, not a nudged counter — `services/panel.py:59`
- §3.3 — insert — ambiguity — supersession increments the superseded appraisal's own `version` — `routes/appraisals.py:100`
- §3.3 — revise — mismatch — comparable addition is not ownership-checked; any `AMCCoordinator` may add a row — `routes/appraisals.py:133`
- §3.3 — insert — ambiguity — `included_in_grid` filter reads trimmed case-insensitive `true`/`false`; any other value matches nothing — `validate.py:198-207`
- §3.4 — revise — mismatch — re-run availability keyed only on the three review statuses; a `RETURNED_TO_AMC` report has an unlocked grid yet answers `ERR_INVALID_STATE` — `routes/appraisals.py:203`
- §3.4 — insert — ambiguity — run answers 200 with the updated appraisal, not the eight rows — `routes/appraisals.py:208`
- §3.4 — insert — ambiguity — distance observed value always rendered at two decimals — `services/appraisal.py:128`
- §3.4 — insert — ambiguity — empty-grid reconciliation records observed value `"0"` — `services/appraisal.py:166`
- §3.5 — revise — mismatch — the screen reads no `review_status` and imposes no grid lock (the old "requires the grid is not locked" claim was false) — `routes/appraisals.py:223-235`
- §3.5 — insert — ambiguity — re-run permitted only from `NOT_SCREENED`/`CLEAR`/`INDICATED`; `SUBSTANTIATED`/`CLEARED_ON_REVIEW` → `ERR_INVALID_STATE`; response is the appraisal — `routes/appraisals.py:231`
- §3.5 — insert — ambiguity — a re-run may move `INDICATED → CLEAR`, restating from the fresh index alone — `services/bias.py:49`
- §3.5 — insert — ambiguity — adjudication answers 200 with the flag; `SUBSTANTIATE` only from `OPEN`, and any disposition on `CLEARED` → `ERR_INVALID_STATE` — `routes/appraisals.py:321-325,393`
- §3.5 — insert — ambiguity — `bias_screen_status` moves only on the `INDICATED` edge; a `CLEAR`/`CLEARED_ON_REVIEW` screen is left alone while `review_status` still quarantines — `routes/appraisals.py:340`
- §3.5 — revise — mismatch — loan `collateral_status` → `QUARANTINED` only from `VALUE_ACCEPTED`/`VALUE_REVISED`; otherwise the loan is unwritten — `routes/appraisals.py:346`
- §3.5 — revise — ambiguity — second-appraisal order release keyed on the appraiser's standing after the recompute, moved or not — `routes/appraisals.py:353`
- §3.5 — insert — ambiguity — quarantine also reachable from `RECEIVED`/`ESCALATED`/`RETURNED_TO_AMC`/`VALUE_CONTESTED`; `SUPERSEDED` → `ERR_INVALID_STATE`; a repeat substantiation keeps the first snapshot — `routes/appraisals.py:330,337`
- §3.5 — revise — mismatch — appeal restores collateral only when the loan actually reads `QUARANTINED` — `routes/appraisals.py:377`
- §3.5 — insert — ambiguity — communication `body` may be empty; no ownership rung on recording one — `routes/appraisals.py:251-257`
- §3.6 — revise — mismatch — the rung-11 open gate admits `RECEIVED` so rung 13 can answer `ERR_RULE_CHECKS_NOT_RUN` — `routes/desk_reviews.py:33-38`
- §3.6 — revise — mismatch — the `UNDER_REVIEW` collateral write is unconditional and bumps the loan's `version` — `routes/desk_reviews.py:62-63`
- §3.6 — insert — ambiguity — any `AppraisalDeskReviewer` may submit, not only the opener; SoD compares `submitted_by_user_id` — `routes/desk_reviews.py:84,112`
- §3.6 — insert — ambiguity — `ACCEPT` on an `INDICATED` screen → `ERR_ESCALATION_REQUIRED`; `SUBSTANTIATED` answers `ERR_BIAS_QUARANTINE_ACTIVE` first, and that gate applies to all three actions — `routes/desk_reviews.py:131-134`
- §3.6 — insert — ambiguity — `ESCALATE` and `RETURN` leave the loan file entirely unwritten (no `updated_at`, no `version`) — `routes/desk_reviews.py:149-178`

Confirmed no `cp`/`Write`: line-level diff showed pass 1's 19 changed lines byte-identical and untouched.

### Pass 3 — 23 pins via 23 Edit calls over 21 lines (17 ambiguity-pins, 6 mismatch-revisions); 131,955 → 138,665 chars

Cross-section fixes where earlier-pass prose mis-stated pass 3's partition:
- §2.3 — revise — mismatch — "every list filter is an exact-match comparison against the raw query-string value" was universally false; named the three typed filters (`included_in_grid`, `admissible`, `round_number`) as the exceptions — `routes/rov.py:139-144`
- §2.8 — revise — mismatch — "One endpoint deliberately departs from the ascending order" → two; added ROV routing, where the quarantine gate (rung 21) is hoisted above the review-status gate (rung 11) — `routes/rov.py:160-164`
- §3.3 — revise — mismatch — "that is the one boolean-valued list filter in the system" → one of two, the other being evidence `admissible` — `routes/rov.py:139-141`

§3.7 escalation orders:
- §3.7 — revise — ambiguity — panel-membership gate reads the order's own `amc_id` and ignores `coverage_state` — `routes/common.py:80-95`, `routes/escalation_orders.py:63`
- §3.7 — insert — ambiguity — a body carrying *neither* window endpoint is `ERR_INVALID_REQUEST` (rung 8), not `ERR_INVALID_WINDOW` — `routes/escalation_orders.py:50-53`
- §3.7 — insert — ambiguity — an order past `due_at` has negative hours remaining and is therefore always rush — `services/escalation.py:25-26`
- §3.7 — revise — mismatch — completion evaluates the quarantine gate *before* the revision cap (prose had them reversed) — `routes/escalation_orders.py:127-131`
- §3.7 — revise — ambiguity — completion writes `value_of_record_appraisal_id` and `collateral_status` as plain assignments, not guarded edges — `routes/escalation_orders.py:145-148`

§3.8 reconsideration of value:
- §3.8 — insert — ambiguity — borrower ownership is compared against the raw body value before FK resolution; absent/non-string `loan_file_id` falls to the body-shape rung — `routes/rov.py:39-45`
- §3.8 — insert — ambiguity — `sale_price_cents` > 0 and `distance_miles` ≥ 0; evidence filing has **no** parent-status gate; filing touches parent `updated_at` without bumping `version` — `routes/rov.py:105-107,25-31`
- §3.8 — revise — mismatch — routing gate order corrected to impl/ladder order, plus the previously unstated `ERR_INVALID_STATE` review-status gate and the quarantine precedence; `intake_note` is overwritten from each call — `routes/rov.py:158-175`
- §3.8 — insert — ambiguity — `VALUE_REVISED` with no `revised_value_cents` is `ERR_INVALID_REQUEST` ahead of the state gate; a value sent with `VALUE_AFFIRMED` is ignored — `routes/rov.py:195-196,212-213`
- §3.8 — insert — ambiguity — either disposition sets `value_of_record_appraisal_id` only when the loan had none — `routes/rov.py:219-228`
- §3.8 — insert — ambiguity — next-round touches neither the appraisal's `review_status` nor the loan — `routes/rov.py:251-260`
- §3.8 — insert — ambiguity — evidence filters are typed; unparseable values match nothing and yield an empty page — `routes/rov.py:139-144`

§3.9 disputes and the revision ledger:
- §3.9 — revise — mismatch — the AMC-standing gate is evaluated ahead of the party gate — `routes/disputes.py:39-43`
- §3.9 — insert — ambiguity — a slot with neither endpoint is `ERR_INVALID_REQUEST` — `routes/disputes.py:32-35`
- §3.9 — insert — ambiguity — a second AMC relay from `APPRAISER_RESPONDED` is `ERR_INVALID_STATE` — `routes/disputes.py:112-113`
- §3.9 — insert — ambiguity — `OVERTURNED` without `resolved_value_cents` is `ERR_INVALID_REQUEST` at rung 8; overturning sets the VOR pointer only when null and touches neither status dimension — `routes/disputes.py:146-147,179-185`
- §3.9 — insert — ambiguity — `BY_DEFAULT` from `APPRAISER_RESPONDED` is `ERR_INVALID_STATE`, checked before the deadline gate — `routes/disputes.py:153-159`
- §3.9 — revise+insert — ambiguity — `prior_value_cents` falls back to `reported_value_cents`; zero base records `delta_bps` 0; `documentation_note` may be null; a ledger write refreshes the appraisal's `updated_at` without bumping `version` — `services/revision.py:9-11,37-38,28-29`
- §3.9 — insert — ambiguity — the cap uses the same null fallback and is not enforced when the base is null or zero — `services/revision.py:14-18`

Confirmed no `cp`/`Write`: all 36 earlier-pass-edited lines outside pass 3's 21 still differ from `PRD_FINALIZED.md`; the 3 shared lines (78, 159, 211) were amended in place, not reverted.

### Orchestrator verification

`wc -l -c`: `PRD.md` 459/118,600 → `PRD_FINALIZED.md` 459/119,074 → `PRD_COMPLETED.md` 459/138,665. `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (57 changed lines, +19,591 chars over the Step 8 output — the scan genuinely ran, per the known failure mode where an identical file means the pass never executed). File tail ends on the final row of the §5 error table, a real section boundary. Total across the three passes: 75 pins (55 ambiguity, 20 mismatch). Step 9 edits touch PRD prose only — `implementation/` and the test artifacts are unchanged since the clean 8-round sweep, so the 163/163 result stands.

**Pipeline complete.**
