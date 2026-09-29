# Worklog — task_2259_teaching_artist_roster_school_residencies

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2259_teaching_artist_roster_school_residencies/` and `tasks/task_2259_teaching_artist_roster_school_residencies/workspace/`.

## Step 2: Generate scaffold — 2026-09-01T13:29:00.000Z

Scaffold generation for task 2259 is complete and lint-clean.

## Linter verdict (verbatim, final run)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2259_teaching_artist_roster_school_residencies/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2259_teaching_artist_roster_school_residencies/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2259_teaching_artist_roster_school_residencies/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    46
  §1.1 entities declared:     12
  §1.8 instances scanned:     22
  §1.9 instances scanned:     58
  Calls scanned (§1.8+§1.9):  1612

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

(An earlier run reported 6 × "(d) capture JSONPath unresolvable" — captures reading calculation intermediates such as `billed_minutes`, or parent-entity fields such as `available_cents` / `portfolio_mean_composite`, off a `Session`/`PortfolioReview` response. Each was fixed by capturing a declared field on the responding entity and, where needed, adding a follow-up `GET` of the parent entity; assertions were rewritten accordingly, preserving all verified numeric literals.)

## Files produced (exactly three)

- `SCAFFOLD.yaml` — §1.0–§1.7 only; contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`.

(`worklog.md` and `workspace/` were already in the directory before generation started; untouched.)

## Scaffold census

- Scenario text: verified byte-identical to the supplied description.
- `complexity_profile.difficulty_level: expert_plus` — deliberately above the §0.4 Expert band (10–15 entities / 20–32 endpoints / 18–30 errors).
- **Entities: 12** — SchoolPartner, CalendarBlackout, TeachingArtist, PortfolioReview, BackgroundScreening, ArtsStandard, Residency, LessonPlan, Session, EvaluationRecord, PaymentVoucher, FunderReport (flat topology).
- **State machines: 7 blocks**, parallel-axis shaped (TeachingArtist runs independent `vetting_status` and `roster_status` axes; PaymentVoucher is a fork/join over FISCAL + PROGRAM review tracks with a reject/resubmit cycle).
- **Concurrency rules: 3** OCC guards — `ERR_STALE_RESIDENCY_VERSION` on `POST /sessions`, `ERR_STALE_SESSION_VERSION` on `/reassign`, `ERR_STALE_VOUCHER_VERSION` on `/payment-vouchers/{id}/review`.
- **Calculations: 16** — incl. `session_fee` (discipline base × grade multiplier × tier multiplier + lead premium + bilingual premium, substitute at 85 %, cap-before-prorate, 5-minute billing rounding), `session_interval_conflict` (half-open intervals, 45-minute travel buffer, school aggregate capacity), `portfolio_composite`, `artist_clearance_window`, `residency_cost_outlook`, `artist_reliability`, `residency_evaluation_index`, `funder_report_rollup`.
- **Validations: 27 ordered priorities** — auth (1–2, 6) / existence & shape (3–5) / OCC (7) / state (8) / business safety, fiscal, temporal and capacity gates (9–27).
- **Endpoints: 46**; every one is exercised by at least one design instance (verified: zero unused endpoints).
- **Error catalog: 54 codes**; all 54 appear in the design files (verified: zero uncovered codes).
- **RBAC roles: 6** — ProgramDirector, RosterCoordinator, CurriculumSpecialist, FiscalOfficer (opaque), TeachingArtist (`entity_backed:TeachingArtist`), SchoolLiaison (`entity_backed:SchoolPartner`); segregation-of-duties role model (panelist ≠ demo evaluator, fiscal ≠ program reviewer, compiler ≠ certifier).

## §1.8 / §1.9 instance counts

- **§1.8: 9 rules / 22 instances** — dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 2, resource_temporal_overlap 3, compensating_invariant 2 (every rule ≥ 2).
- **§1.9: 82 instances across all 9 sections** — Entities 13, State Machines 16, Calculations 12, Validations 8, Endpoints 4, Errors 16, RBAC 6, Cross-Cutting Complexity Layers 6, Consistency Model 1. Of these, **58 carry full test recipes** and **24 are `excluded_because` stubs**, every stub citing a `difficulty_instance` name that exists in `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (verified programmatically) and carrying no `test_recipe`. 60 distinct `claim_type` values are used.

## Step 3: Copy shared files — 2026-09-01T13:31:00.000Z

Copied `INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T13:47:00.000Z

All three hard contracts pass. Final verification summary:

## PRD produced

`workspace/PRD.md` — **534 lines, ~13,200 words**.

### Section structure

- **§1 Introduction** — 3 paragraphs derived from `scenario`: the arts-education problem (screening lapses, untracked make-up credits, double-counted funder headcounts), the scope of the API, and the two framing commitments (structural child-safety/segregation-of-duties; two conserved quantities per residency).
- **§2 Global Specifications** — 12 subsections: 2.1 Operator Identity & RBAC (all 6 roles, `X-User-ID`/`X-User-Role` binding semantics for the two `entity_backed` roles vs. the four opaque ones); **2.2 API Response Structure — emitted byte-verbatim from `section-2.2-response-structure.md`** (verified by exact substring match); 2.3 Pagination; 2.4 Record Identity/Timestamps/Logical Clock (incl. the four `common_fields: false` types carrying only `id` + `created_at`, and the `2026-08-01T00:00:00Z` startup default); 2.5 Money/Rounding/Basis Points (round-half-up, two pinned rounding orders); 2.6 Version Stamping (all 3 OCC rules with per-rule rationale for why no state precondition catches the race); 2.7 Cascade Discipline (Cascade A and B named and outlined); 2.8 Nested Retrieval & left-to-right path/body resolution; 2.9 the full 27-tier global rejection order; 2.10 Child Safety as a Standing Gate; 2.11 Segregation of Duties; 2.12 The Two Conserved Quantities (session-ledger and money invariants).
- **§3 Business Logic** — 9 domain-grouped subsections: 3.1 Recruiting (portfolio/demo/screening), 3.2 Roster Standing/Reliability/Effective Tier, 3.3 School Partnerships & Calendars, 3.4 Scoping & Driving a Residency, 3.5 Curriculum Alignment, 3.6 Scheduling Sessions, 3.7 Delivery/Substitute Coverage/Cancellation, 3.8 Vouchers & Two-Track Review, 3.9 Evaluation & Funder Reporting.
- **§4 Endpoint Definitions** — one lead paragraph on 201-for-create / 200-for-modify, then a 4-column table (Method, Path, Description, Authorized Role(s)) with **46 rows**.
- **§5 Error Code Catalogue** — 2-column table with **54 rows**.

### Coverage audit vs. scaffold

| Scaffold section | Scaffold count | PRD | Check |
|---|---|---|---|
| §1.1 entities / field names | 12 / 150 | 150 | exact |
| §1.2 state machines / transitions | 7 axes / 56 | 7 / 56 | all states + transitions present |
| §1.2.1 concurrency rules | 3 | 3 | §2.6 + in-flow |
| §1.3 calculations | 16 | 16 | all named constants present |
| §1.4 validations | 27 priorities | 27 tiers in §2.9 | ordering reproduced |
| §1.5 endpoints | 46 | 46 | zero missing, zero extra |
| §1.6 errors | 54 | 54 | every HTTP status matches |
| §1.7 roles | 6 | 6 | identity semantics per role |

### Hard Contract reports

- **Contract 1 — Field-Name Coverage: PASS.** Mechanical diff of all 150 `entities[].fields[].name` values and all 111 endpoint identifiers (`request_body` / `input` / `query_params` / `path_params` + path placeholders) against the PRD's backticked tokens: **0 missing** in both sets.
- **Contract 2 — Rule Coverage: PASS.** Validation priority ordering emitted as an explicit 27-tier list; all 3 OCC rejections given individual why-no-state-check rationale; both 4-hop cascades written out link-by-link (A in §3.2/§3.1, B in §3.7) plus delivery's funder-report invalidation and voucher approve/void ledger moves; every `validations[].applies_to` endpoint set enumerated in prose (ownership 8 ops, `ERR_ARTIST_NOT_CLEARED` 6, `ERR_CLEARANCE_EXPIRED` 4, roster 4, capability 4, budget 4, segregation 3, blackout 2, interval 2, capacity 2, temporal 3, linkage 2); field-level defaults and structured content stated (incl. the type-exclusive `EvaluationRecord` null rules and all artist intake defaults); sibling-branch symmetry written at equal density for `DEMO_PASSED`/`DEMO_FAILED`, the two reassign branches, the three `CANCELLED_SCHOOL` source states, the two `CANCELLED_ARTIST` source states, voucher `PASS`/`FAIL`, and both `VOIDED` entries. All 56 transitions, all 16 calculations, every condition→`error_id` pair, and every `endpoints[].side_effects` bullet are represented. No pseudocode: a scan for `:=`, `==`, `>=`, `<=`, `!=`, `min(`, `max(`, `ceil(`, `floor(`, `round_half_up` in §§2–5 returned zero hits, and no fuzzy quantifiers are present.
- **Contract 3 — §3 Path Purity: PASS.** Every backticked token in §3 scanned: **0** start with `/`, **0** are a bare HTTP method, **0** combine method + path. Operations are framed as state transitions (`PLANNED → CONFIRMED`), role+action verbs, or capability descriptions.

Notes: the two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced, and no sibling task directory was read. One consequence worth flagging: the scaffold's inline worked example in the `session_reimbursement` comment (`10.5 mi + 4.5 mi ... 704 + 302 = 1006 vs 1005`) was deliberately *not* copied into the PRD — only the rule it illustrates ("round per session, then sum") is stated, so no worked arithmetic leaks to the implementer. No audit footer was added inside `PRD.md`.

## Step 5: Generate unit tests — 2026-09-01T14:35:00.000Z

Step 5 is finished and globally verified.

## Final state on disk

`test_helpers/` — 9 files, untouched since Stage 1 (all mtimes precede queue B; no corner instance needed a new fixture).

`test_suite/` — `conftest.py` + 17 test modules, **124 tests**, all collected by pytest without error:

| file | tests | queue |
|---|---|---|
| test_01_roster_vetting_and_child_safety.py | 8 | A |
| test_02_residency_lifecycle_and_curriculum.py | 3 | A |
| test_03_session_scheduling_conflicts.py | 8 | A |
| test_04_session_fee_and_reimbursement.py | 6 | A |
| test_05_cost_outlook_and_reliability.py | 6 | A |
| test_06_voucher_review_and_money.py | 6 | A |
| test_07_makeup_credits_and_cancellation.py | 4 | A |
| test_08_funder_reporting.py | 4 | A |
| test_09_entities_and_reads.py | 14 | B (Entities, 13 instances) |
| test_10_state_machines.py | 11 | B (State Machines, 11) |
| test_11_calculations.py | 11 | B (Calculations, 6) |
| test_12_validations.py | 7 | B (Validations, 4) |
| test_13_endpoints.py | 7 | B (Endpoints, 4) |
| test_14_errors.py | 12 | B (Errors, 9) |
| test_15_rbac.py | 8 | B (RBAC, 6) |
| test_16_concurrency_and_reconciliation.py | 7 | B (Cross-Cutting Complexity Layers, 4) |
| test_17_consistency_model.py | 2 | B (Consistency Model, 1) |

**Queue A: 45 tests / 22 of 22 non-stub §1.8 instances. Queue B: 79 tests / 58 of 58 non-stub §1.9 instances. Coverage is complete on both queues; nothing was skipped.**

## Correction to the coordinator's premise

The seven parallel agents were **not** lost — they were still live and all seven completed during this turn, writing `test_09`–`test_17` directly to `test_suite/`. My own hand-written `test_09_entities_and_reads.py` was superseded by the Entities agent's larger version (I could not stop the agents: `TaskStop` refused, "owned by" the agent itself). Rather than race them file-for-file, I let them land and then re-derived the whole verification myself from scratch, which is the part that actually gates Stage 2.

## Independent verification I ran over all 124 tests

- **Design tags:** 124 tags, exactly one per test and always the docstring's last line; zero untagged, zero dual-tagged. Every tag parsed and resolved against a freshly built index of both YAMLs: 80 distinct `(queue, group, name)` triples, all present as a real `name:` key under the correct `section:`/`rule_id:`, **zero pointing at a stub** (the 24 corner stubs and the difficulty stubs are untranslated and unmentioned).
- **Citations:** 427 quotes checked. Each normalises to a verbatim substring of a `workspace/PRD.md` line, and each cited `§n.m` matches the nearest preceding heading of the line the sentence actually lives on — 0 verbatim failures, 0 section mismatches. Every test carries 2–4 citations. Two "incomplete sentence" flags are artifacts of my own terminator heuristic (one PRD sentence contains nested `"object"`/`"array"` quotes; one is wrapped in `**bold**`); both are genuine complete PRD sentences.
- **Structure:** every test takes `api` as its first parameter; no `xfail`, `pytest.skip`, `mark.skip`, `TODO`, or scaffold/design vocabulary (`claim_type`, `test_recipe`, `excluded_because`, …) anywhere; no reference to `workspace/implementation/` or any sibling task path.
- **Mechanics:** `py_compile` clean; `pyflakes` clean across all 17 modules (I removed two stale unused imports from `test_01`); every module imports successfully; every `api_client.<method>` used exists on the client; `pytest --collect-only` → 124 tests, no duplicate-name shadowing; `__pycache__` removed.

## Instances skipped

**None.** No non-stub instance failed the PRD-first two-condition filter. What was dropped is narrower — individual sub-claims inside otherwise-testable instances, where the YAML asserted something the PRD does not state or the API cannot observe:

- "no PATCH/PUT/DELETE exists for `CalendarBlackout`" and "no `SchoolPartner` row was persisted" — no endpoint exists to probe either; replaced by the §2.4 absence of `version`/`updated_at` and by a PRD-derivable positive control.
- `Residency.students_served_encounters` — no such field anywhere in the PRD.
- Any staffing/health cascade on artist *retirement* — the PRD declares that cascade only for suspension.
- List **ordering** is never asserted: under the pinned logical clock `created_at` can tie, so pagination tests assert filtered `total_count`, `limit`/`offset` echo, `has_more`, page size and set membership instead.

## PRD-over-YAML repairs (the PRD won every time)

- Statuses: `ERR_INSUFFICIENT_PORTFOLIO_REVIEWS` / `ERR_PORTFOLIO_THRESHOLD_NOT_MET` / `ERR_DEMO_ATTEMPT_LIMIT_REACHED` asserted at **409** and `ERR_UNKNOWN_STANDARD_CODE` at **422** per §5 and §2.8, not the YAML's 422/404.
- After a lead artist is suspended the residency is asserted `LEAD_VACANT` (§3.2 link three + §3.4 precedence), not the YAML's `AT_RISK`; after a stale-blocked reassignment finally lands, `vacated_artist_id` is the outgoing artist (§3.7), not null.
- Scenarios that were ambiguous under the PRD were made uniquely-derivable rather than weakened: each capability-mismatch residency now deviates on exactly one dimension; the artifact-rate denominator was made identical under both readings of §3.9; a `DRAFT` residency asserting a 10-session allotment was rebuilt through approval (§3.4).

## Step 6: Generate implementation — 2026-09-01T14:35:00.000Z

The implementation is complete and validated.

## Files written

All under `workspace/implementation/` (3,564 lines total):

**Launcher / infra**
- `start.sh` — reads `$PORT` (default 8080), installs Flask only if missing, `exec python3 app.py` in the foreground
- `requirements.txt` — `Flask==3.0.3`
- `app.py` — app factory, 9 blueprints, global-lock request wrapper, envelope-shaped 400/404/405/500 handlers

**Core**
- `db.py` — 12 in-memory dicts (empty on every boot, never seeded), `new_id()`, `base_row()`, idempotent-per-request `touch()` for version stamping, deterministic `ordered()`
- `clock.py` — logical clock (default `2026-08-01T00:00:00Z`) plus strictly-increasing real wall clock for `created_at`/`updated_at`
- `response.py` — `meta`/`response_type`/`data` envelope, `req_` + 20-alnum request ids, pagination fields on list endpoints only
- `errors.py` — all 54 error ids with their HTTP statuses
- `enums.py`, `validators.py` — typed field coercion with explicit-`null`-equals-absent semantics
- `middleware.py` — header auth, 6-role RBAC, pagination/query parsing

**Services**
- `services/calc.py` — all 16 calculations plus every constant: Decimal/ROUND_HALF_UP money, cap-before-prorate fees, 5-minute billing rounding, 5-bucket session ledger, 3-account money ledger, staffing status, school health, projections, rubric/evaluation indices, funder-report metrics, reliability and tier recomputation, interval/capacity/capability/blackout checks
- `services/derive.py` — computed-on-read serializers for all 12 entities, Cascade A (suspension → vacate → re-staff → health), Cascade B (artist cancel → reliability → probation → tier cap → re-projection), funder-report invalidation

**Routes** — `schools.py`, `artists.py`, `standards.py`, `residencies.py`, `lesson_plans.py`, `sessions.py`, `vouchers.py`, `reports.py`, `clock_route.py`

## Endpoint count

**46 routes**, exactly matching the PRD §4 table (verified against the URL map; e.g. there is deliberately no `GET /school-partners` list, so that path correctly returns an envelope-shaped 405).

## Verification

Two end-to-end smoke suites pass against the in-process app, and a real `PORT=8391 ./start.sh` boot serves live HTTP. Coverage includes: full artist vetting → screening → roster activation, residency lifecycle, lesson-plan alignment, session confirm/deliver/voucher/report/certify happy path (`encumbered_cents` 13750 at confirm; fee 11458 / travel 134 / materials 2500 for 48 delivered minutes; `evaluation_index` 91.8; both conservation identities hold), Cascade A (vacate + encumbrance release + lead clearing + school → WATCH, then re-staffing back to HEALTHY), Cascade B (4 no-shows → reliability 0 → PROBATION → tier capped → confirmation refused), make-up credit issue/consume, blackout and allotment gates, the ACTIVE→SUSPENDED descope sweep with `INTAKE_SUSPENDED` intake blocking, OCC 412s on all three parents, segregation-of-duties refusals, and clock-driven clearance expiry.

## PRD ambiguities resolved by interpretation

1. **Voucher belongs-to check** — a claimed session not belonging to the named residency/artist has no dedicated error; returned `ERR_INVALID_REQUEST` (400).
2. **Ill-ordered voucher/report periods** — `period_end < period_start` treated as `ERR_INVALID_REQUEST`, not `ERR_VOUCHER_PERIOD_MISMATCH`.
3. **`created_at`/`updated_at` use the real wall clock**; only PRD §2.4's enumerated comparisons (plus `aligned_on`) read the logical clock.
4. **Version-bump contract** — SchoolPartner rows never bump (health is derived), `POST /sessions/{id}/evaluations` bumps nothing, and cascades stamp a row only when one of its own *stored* fields actually moves. This resolves a tension between PRD §2.7's derived-field wording and the scaffold's broader `increments` lists.
5. **`projected_cost_cents` is computed on read**, so Cascade B's "re-projection" step writes no residency rows.
6. **Validation precedence** — PRD §2.9's global 27-step order was treated as authoritative wherever a per-endpoint list disagreed (notably confirm, which the scaffold lists with roster before clearance-expiry).
7. **Confirm runs no interval/capacity checks**; reassign runs school capacity but not the blackout check; reassign's screening gate checks only `clearance_status`, while create/confirm check vetting *and* clearance.
8. **Same-artist reassign** is rejected at priority 4 as `ERR_INVALID_REQUEST`, before body-id resolution and the version check.
9. **Body-shaped `ERR_UNAUTHORIZED`** (evaluation `evaluation_type` vs role, voucher `review_track` vs role) evaluated at priority 2, before path resolution, and only for present, valid enum values.
10. **Interval conflicts** — all overlap pairs reported first (`ERR_ARTIST_SCHEDULE_CONFLICT`), then travel buffer; blocking set `{PLANNED, CONFIRMED, DELIVERED}`; school capacity measured as boundary-instant load with the candidate included.
11. **Cancel** — legal from `{PLANNED, CONFIRMED, VACATED}`; artist-side reasons illegal from `VACATED`; any client use of `RESIDENCY_DESCOPED` → `ERR_CANCEL_REASON_NOT_PERMITTED` (it is server-reserved for the descope sweep).
12. **Blackout creation performs no SchoolLiaison ownership check** (the PRD grants the role but names no ownership rule).
13. **Lesson-plan creation** — an acting `TeachingArtist` whose `X-User-ID` resolves to no artist gets `ERR_ACTOR_NOT_RESOURCE_OWNER`.
14. `covered_strands` ordered by first appearance in `standard_codes`; `reviewer_note` stays optional on `REQUEST_CHANGES` and is not persisted by `ALIGN`.
15. **FunderReport metrics are stored snapshots** initialised to 0 and refreshed only on compile; `invalidated_reason` cleared only on a `DRAFT → COMPILED` compile.
16. Minor: `discipline` filter matches primary *or* secondary; evaluations do not require the session to be `DELIVERED`; `makeup_for_session_id` is ignored on `REGULAR`; `decline_reason`/`note` accepted but not persisted; invalid enum/`limit`/`offset` query params → `ERR_INVALID_REQUEST` 400; comma-separated `session_ids`/`scope_residency_ids` filters require *all* supplied ids to match.

## Step 7: Run tests and iterate — 2026-09-01T15:05:00.000Z

All 8 parallel rounds pass at 124/124.

## Summary

**Iterations run:** 2 (each a full 8-round concurrent sweep, `--isolation per-test-server`).

**Sweep 1 result:** 123/124 in every one of the 8 rounds — one deterministic (non-flaky) failure, identical across all rounds:
`test_15_rbac.py::test_an_artist_may_not_report_delivery_of_a_session_held_by_another` → `AssertionError: no delivery figure was recorded, got None (assert None == 0)`.

**Sweep 2 result:** 124/124 in all 8 rounds.

**Tests deleted:** none.

**Fixes applied to `test_suite/`** (STEP 1c partial-coverage split, DEFAULT-VALUE SILENCE):
- `test_suite/test_15_rbac.py`, `test_an_artist_may_not_report_delivery_of_a_session_held_by_another` — the two assertions `session["fee_cents"] == 0` and `session["payable_cents"] == 0` were relaxed to `in (None, 0)`. The only PRD sentence covering these fields' un-delivered state is §3.6: *"A new session is created in `PLANNED` status with `vacated_artist_id`, `payment_voucher_id`, `cancel_reason`, and every delivery and money field still null or zero…"* — an explicit disjunction. Two faithful readers diverge: one stores `null` for a not-yet-measured delivery figure, the other stores `0`; the implementation stores `null` for `fee_cents`/`payable_cents` and `0` for `encumbered_cents`, which the sentence permits. The relaxation encodes exactly the covered rule ("null or zero") and still fails any implementation that records a real fee on a refused delivery. Scaffold rule that drove the test: `Corner/RBAC/teaching_artist_cannot_deliver_another_artists_session`.
- The load-bearing assertions in that test were left untouched and all pass: `ERR_ACTOR_NOT_RESOURCE_OWNER` at HTTP 403, session stays `CONFIRMED`, and the confirmation hold is unchanged at `encumbered_cents == 13974` (verified derivable from PRD §3.7: DANCE 12000 → ×1.05 G3_5 = 12600 → ×0.90 APPRENTICE = 11340 → +1134 lead premium +1500 non-`en` language premium = 13974, within the 9000–19000 clamp at full proration).

**Fixes applied to `test_helpers/`:** none needed — no shared fixture/factory/header-builder bug surfaced.

**Fixes applied to `implementation/`:** none. The single failure traced to a PRD-ambiguous test assertion, not to implementation behaviour; no PRD-required check was removed or weakened, and no data is seeded at startup (storage remains in-memory dicts).

**Flakiness note:** the 8-round sweeps showed zero round-to-round variance in either iteration — the failing test failed in all 8 rounds of sweep 1 and the suite passed in all 8 rounds of sweep 2, so no timing-sensitive concurrency, fixture-ordering, or port-collision defects were surfaced. Transient `results.*.json` files were cleaned out of `workspace/implementation/` afterward.

**Orchestrator note:** Step 7's subagent deleted the `results.*.json` files on exit; the orchestrator re-ran an independent 8-round verification sweep to reproduce the pass state and restore `results.{1..8}.json` on disk (see Step 7-verify below).

## Step 8: Finalize PRD — 2026-09-01T15:12:00.000Z

Done. `PRD_FINALIZED.md` written with a single, surgical edit.

## Line counts
- `PRD.md`: 533 lines; `PRD_FINALIZED.md`: 533 lines; **%-delta: 0.00%** (1 line revised in place, no lines added or removed; 1/533 = 0.19% of lines touched).

## Changes
- **§3.6 (Scheduling Sessions Across School Calendars)** — *revise* — replaced the ambiguous disjunction "every delivery and money field still null or zero" on a newly created session with the exact split the implementation makes: `encumbered_cents` is `0` (and is an integer that is never null), while the four delivery measurements (`students_present_count`, `minutes_delivered`, `travel_miles`, `materials_spend_cents`) and the four computed money figures (`fee_cents`, `travel_reimbursement_cents`, `materials_reimbursement_cents`, `payable_cents`) are all `null`, populated only by the delivery report — `implementation/routes/sessions.py:205-213`.

## Per-edit pre-edit search log

**Edit 1 — §3.6 session-creation defaults**

(a) **Subject identified:** the initial and subsequent values of a session row's delivery-measurement fields, its computed money figures, and its own held amount (`encumbered_cents`) — i.e. null-vs-zero for every field the sentence's "null or zero" disjunction covers.

(b) **Impl paths enumerated (grepped repo-wide for all nine field names, then read each hit):**
- `routes/sessions.py:186-215` — `create_session` row literal (the Step 7 site): eight fields `None`, `encumbered_cents` `0`.
- `routes/sessions.py:305-312` — `confirm_session`: writes `encumbered_cents` only; leaves the eight null.
- `routes/sessions.py:351-362` — `reassign_session` (both `VACATED→CONFIRMED` and `CONFIRMED→CONFIRMED` forms): reads held with `or 0`, writes `encumbered_cents` only.
- `routes/sessions.py:396-399` — `cancel_session` (school-side and artist-side): sets `encumbered_cents = 0`, never nulls the eight.
- `routes/sessions.py:438-455` — `deliver_session`: the *only* writer of all eight fields.
- `services/derive.py:103-116` — `session_view`: pure `_pick`, no defaulting/coercion, so stored `None` is serialized as JSON `null`.
- `services/derive.py:167-177` — Cascade A vacating: `encumbered_cents = 0` only.
- `routes/residencies.py:235-244` — `_suspend` descope sweep: `encumbered_cents = 0` only.
- `routes/vouchers.py:240-246` — `_approve`: zeroes session `encumbered_cents`; `routes/vouchers.py:266-272` — `void`: restores `encumbered_cents = payable_cents or 0`, does not touch the eight.
- `services/calc.py:351-360, 388, 455, 493, 542-548` — every consumer (`budget_ledger`, `earned_to_date_cents`, evaluation-index headcount, encounters headcount, `voucher_total`) reads these fields through `or 0`, confirming null is the real stored state rather than an artifact.

(c) **Wording adjustment made:** two, both to avoid over-claiming. (1) Instead of asserting a universal "money fields are null", I split `encumbered_cents` out explicitly and described it as "an integer that is never null", which matches all nine writers above (init, confirm, reassign, cancel, deliver, Cascade A, descope, approve, void). (2) I phrased the null-persistence claim as "populated only by the delivery report of §3.7, so a session that never reaches `DELIVERED` keeps them null" rather than "stay null until delivered" — verified against the cancel/vacate/descope/void paths, none of which writes or re-nulls the eight fields, so the statement holds on paths Step 7 never exercised.

## Step 7-verify: Orchestrator independent 8-round sweep — 2026-09-01T15:30:00.000Z

The orchestrator re-ran the full 8-round parallel sweep itself (`--isolation per-test-server`, `--timeout 120`, `--test-timeout 30`, free-port-per-round) to independently reproduce Step 7's pass state and to restore the `results.{1..8}.json` artifacts that Step 7's subagent had deleted on exit.

```
round 1: 124 / 124
round 2: 124 / 124
round 3: 124 / 124
round 4: 124 / 124
round 5: 124 / 124
round 6: 124 / 124
round 7: 124 / 124
round 8: 124 / 124
```

Zero round-to-round variance; `workspace/implementation/results.1.json` … `results.8.json` are on disk. This sweep ran after Step 7's final state and before/alongside Steps 8–9 (which touch only PRD files, never `implementation/` or the tests), so it reflects the shipped artifacts.

## Step 9: Complete PRD — 2026-09-01T15:32:00.000Z

Deliverable complete: `workspace/PRD_COMPLETED.md`

## Exit summary

- Source `PRD_FINALIZED.md`: **533 lines / 96,772 chars**
- Completed `PRD_COMPLETED.md`: **533 lines / 104,846 chars** → **char delta +8,074**, line delta **0** (every change was an in-paragraph insert or sentence revision; no new sections, no new paragraphs)
- **32 changed lines / 30 edits**: **24 ambiguity-pins**, **6 mismatch-revisions**

### Mismatch-revisions (6)

- **§2.7 Cascade discipline** — revise — mismatch — version increments are at most once per row per request and follow *stored* fields, not recomputed ones: `SchoolPartner` is never stamped after creation, a residency is not stamped for tier-driven re-projection nor for Cascade-A vacating that neither releases money nor clears the lead, and an artist is not stamped when reliability/roster/tier are unchanged — `db.py:43-66`, `middleware.py:80-94`, `derive.py:157-191,218-226`, `sessions.py:459-465`
- **§2.12 Two conserved quantities** — revise — mismatch — the five-bucket identity holds from approval onward; a `DRAFT` residency reads zero in all five buckets and all three money accounts — `residencies.py:107-110`, `calc.py:355-358`
- **§3.3 School partnership health** — revise — mismatch — `partnership_health` and `open_residency_count` are recomputed on every read; the school row is never written, `updated_at`-refreshed, or version-stamped by residency activity — `calc.py:374-383`, `middleware.py:80-94`
- **§3.7 Session reassignment** — revise — mismatch — reassign splits the gates: clearance window → `ERR_ARTIST_NOT_CLEARED`, session date past clearance → `ERR_CLEARANCE_EXPIRED`, `vetting_status`/`roster_status` → `ERR_ARTIST_NOT_ON_ACTIVE_ROSTER`; the candidate session is excluded from its own blocking set; an existing `vacated_artist_id` is left untouched on the `VACATED → CONFIRMED` form; substitute-rate held amount still carries the lead premium when the substitute is the lead — `sessions.py:335-362`
- **§3.8 Voucher creation** — revise — mismatch — a claimed session not belonging to the named residency/artist is `ERR_INVALID_REQUEST` evaluated *after* the ownership check rather than at §2.9's payload priority; creation does not require sessions to be `DELIVERED`; the three linkage rules apply in listed order — `vouchers.py:84-94`
- **§3.9 Evaluation attachment** — revise — mismatch — attaching an evaluation has no session-status precondition; only the evaluation index and the voucher evidence gate (both `DELIVERED`-only) decide whether it counts — `sessions.py:472-525`

### Ambiguity-pins (24)

- **§2.2** — insert — ambiguity — `api_request_id` is `req_` plus exactly 20 uppercase-letter/digit characters — `response.py:13`
- **§2.3** — revise — ambiguity — `offset` may not be negative; non-integer or out-of-bounds `limit`/`offset` are rejected with `ERR_INVALID_REQUEST` rather than clamped; empty string treated as absent — `middleware.py:29-47`
- **§2.3** — insert — ambiguity — `has_more` is true exactly when `offset` + returned count < `total_count` — `response.py:36`
- **§2.3** — insert — ambiguity — global filter semantics: omitted/empty drops the filter, out-of-domain enum or malformed date → `ERR_INVALID_REQUEST`, unmatched identifier filter yields an empty page not a not-found code — `middleware.py:60-95`
- **§2.4** — insert — ambiguity — `to_iso8601` is a required string and an offset-less instant is read as UTC; `created_at`/`updated_at` are stamped from the real wall clock, not the logical clock; `aligned_on` is the only logical-clock-written field — `clock_route.py:18-24`, `clock.py:36`, `db.py:35`
- **§2.9 item 2** — revise — ambiguity — the two role-shaped `ERR_UNAUTHORIZED` mismatches (`review_track`, `evaluation_type`) fire at priority 2, before path identifiers resolve — `vouchers.py:195-200`, `sessions.py:475-480`
- **§2.9 item 4** — insert — ambiguity — explicit JSON `null` counts as absent everywhere: it fails a required field and takes the default for an optional one — `validators.py:63-76`
- **§3.1** — revise — ambiguity — artist email uniqueness is exact string comparison with no address-format validation — `artists.py:63,72`
- **§3.1** — revise — ambiguity — a demo score on the wrong side of 3.5 for the named branch is `ERR_INVALID_STATE_TRANSITION`; the segregation check is evaluated only after the threshold — `artists.py:150-160`
- **§3.1** — insert — ambiguity — a `FAILED` screening recorded from any other vetting state is stored but moves neither axis; the clearance reset for an already-`CLEARED` artist is permanent (sticky) — `artists.py:325-330`, `calc.py:183-185`
- **§3.4** — insert — ambiguity — lead-artist assignment has no residency-`status` precondition, terminal states included — `residencies.py:146-163`
- **§3.4** — insert — ambiguity — a borrowed lead on a `VACATED` session supplies tier and language only (no lead premium); with no lead at all the projection falls back to `TEACHING_ARTIST` with no lead/language premium; session `is_substitute` is honoured — `calc.py:403-411`
- **§3.5** — revise — ambiguity — `covered_strands` are the distinct strands in order of first appearance, left to right — `lesson_plans.py:29-35`
- **§3.5** — insert — ambiguity — a TeachingArtist `X-User-ID` matching no artist row → `ERR_ACTOR_NOT_RESOURCE_OWNER`; a RosterCoordinator authoring against a leadless residency leaves `author_artist_id` null; no residency-status precondition — `lesson_plans.py:60-66`
- **§3.5** — revise — ambiguity — `reviewer_note` is optional and stored null when omitted — `lesson_plans.py:126`
- **§3.5** — revise — ambiguity — ALIGN re-derives `covered_strands` and leaves an earlier `reviewer_note` in place — `lesson_plans.py:144-150`
- **§3.6** — insert — ambiguity — body ids resolve in the order `residency_id`, `assigned_artist_id`, `lesson_plan_id`, `makeup_for_session_id`; a `makeup_for_session_id` on a `REGULAR` request must still resolve (`ERR_SESSION_NOT_FOUND`) before being discarded as null; no residency-status precondition — `sessions.py:134-139,192`
- **§3.6** — revise — ambiguity — both confirmation fields are required — `sessions.py:276-277`
- **§3.7** — insert — ambiguity — all four delivery measurements are required; three are integers ≥ 0 with no upper bound, `travel_miles` is a number ≥ 0 with at most one decimal — `sessions.py:415-418`
- **§3.7** — revise — ambiguity — the `substitute_artist_id` differ-check is a priority-4 payload check firing before identifier resolution and before the version check; the second form shares the same clearance/roster code split — `sessions.py:326-327`
- **§3.8** — revise — ambiguity — the voucher `session_ids` list filter is one comma-separated value matching vouchers that contain every listed id — `vouchers.py:137-139`
- **§3.8** — revise — ambiguity — `void_reason` is required — `vouchers.py:243`
- **§3.9** — revise — ambiguity — the artifact-rate denominator is the headcount across *every* delivered session of the residency, not only those carrying a sample — `calc.py:497-505`
- **§3.9** — revise — ambiguity — the report `scope_residency_ids` filter is comma-separated and all-must-be-present — `reports.py:89-92`
- **§3.9** — revise — ambiguity — `certifier_user_id` and `attestation_text` are both required — `reports.py:123-124`
- **§3.9** — insert — ambiguity — compile against a `CERTIFIED` report is refused with `ERR_INVALID_STATE_TRANSITION` — `reports.py:103-104`
- **§4** — insert — ambiguity — an unlisted path returns `ERR_INVALID_REQUEST` at HTTP 404 and an undeclared method on a listed path returns `ERR_INVALID_REQUEST` at HTTP 405 — the only places an `ERR_INVALID_REQUEST` body is not HTTP 400 — `app.py:65-72`

### Deliberately left unchanged

- Ordering that §2.9's 27-priority list already determines uniquely (clearance before underdelivery at delivery; invalid-state before not-cleared on reinstatement; `ERR_ARTIST_NOT_CLEARED` before `ERR_RELIABILITY_BELOW_FLOOR` on probation exit) — the PRD already pins these, so no edit was warranted.
- Unreachable impl branches (`ERR_NO_ALIGNED_LESSON_PLAN` for an empty `covered_strands` on ALIGN; `ERR_SESSION_ALLOTMENT_EXHAUSTED` on the MAKEUP branch; `derive.reproject_open_residencies` being a bare no-op) were not pinned, since pinning them would describe behavior the implementation never exhibits.
