# Worklog — task_2405_partner_compensation_origination_credit

## Step 1: Create task directory — 2026-09-02T07:53:46.747Z

Created `tasks/task_2405_partner_compensation_origination_credit/` and `tasks/task_2405_partner_compensation_origination_credit/workspace/` (directory name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T09:59:20.713Z

All three artifacts are complete and the linter is green.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2405_partner_compensation_origination_credit/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2405_partner_compensation_origination_credit/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2405_partner_compensation_origination_credit/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    50
  §1.1 entities declared:     12
  §1.8 instances scanned:     25
  §1.9 instances scanned:     58
  Calls scanned (§1.8+§1.9):  1112

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

## Counts
- **§1.1–§1.7**: 12 entities · 50 endpoints · 11 state machines (2 of them on one entity: `CompensationAward.award_state` × `payment_state`) · 10 calculation rules (3 carrying `variants:`) · 17 validation rules (priority ladder 10→140) · 6 concurrency rules · 5 roles · 59 error codes · 6 governance constants. `difficulty_level: expert_plus`, `role_model: segregation_of_duties`, `state_machine_shape: cyclic`, `entity_topology: graph`.
- **§1.8**: 9 rule_ids × 2–3 instances = **25 instances**.
- **§1.9**: **9 sections, 89 instances** — 58 with full executable recipes, 31 `excluded_because:` stubs (entities 11, state_machines 16, calculations 14, validations 9, endpoints 5, errors 17, rbac 7, cross_cutting 9, consistency_model 1).
- Verified independently: all 59 error codes are triggered by at least one instance; no name collides across the two design files; every stub has `grounds` + `excluded_because: {difficulty_instance, rationale}` citing a real §1.8 instance and no `test_recipe`.

## Notable design decisions
- **Three cyclic loops, each with its own pinned bound**: `CreditClaim DISPUTED→DRAFT` (MAX_REMANDS 2), `SelfAssessment SUBMITTED→DRAFT` (destroys SCORED peer reviews, so the loop is expensive), `CompensationCycle AWARDS_PUBLISHED→DELIBERATION` (MAX_REOPENS 1, appends DRAW_REVERSAL rows).
- **Two independent state dimensions** on `CompensationAward` (`award_state` × `payment_state`) plus a `credited_collection` provisional/final variant pair and a contribution/fully-loaded profitability variant pair — four dual-variant surfaces.
- **Origination credit as an interval-capacity problem**: `CreditAllocation` is a role-qualified Partner×Matter junction with half-open `[credit_from, credit_through)` windows; the 100.00 % cap is an overlap-aggregate check, and partner departure moves credit by closing one interval and opening another (with an exact compensating void).
- **Three OCC parents** (Matter, CompensationCycle, Partner) across 6 rules; every ballot cast bumps the cycle version, so serial deliberation is provably observable.
- Two reachability bugs found and fixed while auditing §1.5 during §1.9 generation: `ERR_CYCLE_NOT_REOPENABLE` was unreachable (fixed by introducing `MAX_REOPENS`), and the true-up corner initially called `/true-up` from `payment_state PENDING`, which the payment machine refuses. Also tightened §1.4: priority-50 now enumerates `ERR_ALLOCATION_NOT_FOUND`/`ERR_PAYMENT_NOT_FOUND`, priority-100 now lists `POST /comp/peer-reviews`, and `Matter OPEN→WRITTEN_OFF` now declares the `responsible_matter_count` decrement.

## Step 3: Copy shared files — 2026-09-02T09:59:20.713Z

Copied `INSTRUCTION.md` → `tasks/task_2405_partner_compensation_origination_credit/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T10:16:16.655Z

PRD generated at `workspace/PRD.md`.

**Line count:** 487 lines.

**Section inventory**
- §1 Introduction — 3 paragraphs (spreadsheet pain point, scope, two binding commitments: immediate reconciliation + append-only cash ledger).
- §2 Global Specifications — 12 subsections: 2.1 Actors/Auth/RBAC · 2.2 API Response Structure (verbatim fixed block) · 2.3 Pagination · 2.4 Resource Identity, Timestamps, Version Semantics · 2.5 The Logical Clock · 2.6 The Anchor Cycle · 2.7 Precision & Rounding · 2.8 Stale-Version Guards · 2.9 Derived Fields, Cascades, Half-Open Credit Window · 2.10 Reference Resolution Order · 2.11 The Validation Precedence Ladder · 2.12 Confidentiality of Committee Deliberation.
- §3 Business Logic & Workflows — 9 subsections: partner roster/departure · matters & matter economics · contribution records & non-billable weighting · origination claims & adjudication · credited collections & formula score · self-assessment & peer review · deliberation & discretionary points · cycle staging, pool waterfall, award publication · draws, true-up, capital settlement, closure.
- §4 API Endpoints — 4-column table, 50 rows, with a status-code/path-parameter preamble.
- §5 Data Validation & Error Handling — 2-column table, 59 rows. File ends here; no audit footer.

**Hard Contract results**
- **Contract 1 (field-name coverage): PASS.** Two independent extraction passes. Pass 1 (148 required names: 133 entity fields + request-body-only identifiers + `id`): 0 missing. Pass 2 (independent YAML walk, 159 `- name:` values + 87 normalized request_body/input/query_params/path_params keys): 0 missing after stripping the scaffold's optional-marker `?` suffix. The only pass-2 residuals were the 12 entity type names and 10 calculation rule ids, which are scaffold-internal identifiers not covered by the contract (each is expressed in prose; `DrawPayment` is also named literally in §2.4). All 59 error ids appear (the 60th regex hit, `ERR_XXX`, is a placeholder inside a scaffold description).
- **Contract 2 (rule coverage): PASS.** All 40 transitions across the 11 state machines are described, including the 9 the arrow-literal scan flagged, which are written as multi-source prose ("from either `SUBMITTED` or `DISPUTED`", "keeps it in `DRAWING`", "Voiding from `PROPOSED`/`EFFECTIVE`"); `NOTICE_GIVEN → DEPARTED` was additionally given its explicit arrow form. All 10 calculations are prosified step-by-step with every constant, rounding point and zero-guard, including the 3 that carry variants (realization/profitability, credited-collection provisional vs final, award provisional vs final). All 17 validation rungs appear in order with their error ids and `applies_to` scopes, plus the 3 named priority conflicts as worked cases. All 6 concurrency rules are enumerated with parent entity, `expected_matter_version`/`expected_cycle_version`/`expected_partner_version`, `ERR_STALE_VERSION` 412, and per-rule rationale, with an explicit statement that unnamed endpoints take no version field. Cross-entity side effects, the cascade chains, sibling-branch symmetry (allocate vs split vs reject vs remand; score vs recuse; accept vs return; abstain vs recuse; void-from-PROPOSED vs void-from-EFFECTIVE), and both conserved quantities are covered.
- **Contract 3 (§3 path purity): PASS.** Programmatic scan of every backticked token between the §3 and §4 headers: 0 tokens beginning with `/`, 0 bare HTTP methods, 0 method+path combinations. The `/comp` mount is mentioned only in §1, §2 and §4.

**Coverage audit, scaffold §1.1–§1.7**
- §1.0 metadata → domain, `/comp` prefix, 5 roles, 6 governance constants all surfaced.
- §1.1 12 entities / 133 fields → all fields backticked, with types, defaults, enum sets and derivation rules; DrawPayment's absent `updated_at`/`version` called out.
- §1.2 11 state machines / 40 transitions → all edges, guards, side effects and terminal states; the 3 bounded cyclic loops (MAX_REMANDS 2, assessment return, MAX_REOPENS 1) and the orthogonal `award_state` × `payment_state` pair described explicitly.
- §1.3 10 calculations → all present with pinned step ordering, dual rounding layers in the credited-collection split, and the eight-step formula-score order.
- §1.4 17 validations + 3 conflicts → the §2.11 ladder.
- §1.5 50 endpoints → the §4 table, plus every request field placed in §3 prose.
- §1.6 59 errors → §5 table plus in-prose trigger conditions.
- §1.7 concurrency → §2.8.

**Zero-Silence Rule concerns (two, both resolved by decision rather than invention)**
1. `CreditClaim.counterparty_pct` is contradictory in the scaffold: its field description says "arbiter awarded to the disputer on a SPLIT; null otherwise", but the sharing-convention calculation lists it as an output field. I followed the field description plus the per-branch transition side effects: on an allocate decision `counterparty_pct` stays null and the convention's complement is expressed only as the resolved prior originator's allocation percentage; on a split it carries the disputer's figure. §3.4 states this divergence explicitly so an implementer cannot read it either way.
2. Allocation `source` values on the allocate branch are named explicitly only for split in the scaffold. I assigned `CLAIM_ALLOCATED` to the claimant row and `SHARING_CONVENTION` to the resolved prior originator row, mirroring split, and said so in prose.

No content from `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml` was read, grepped or referenced, and no sibling task directory was accessed. A leak scan confirms the PRD contains no `§1.x` scaffold cross-references, no rule ids, no `test_recipe` material and no pseudocode.

## Step 5: Generate unit tests — 2026-09-02T11:33:00.000Z (artifact recovered on resume)

RESUME NOTE (orchestrator): Step 5 was executed by a prior run of this pipeline, but its worklog entry was never written before the run terminated. The artifacts satisfy the resume protocol's check #4 and were therefore NOT regenerated: `test_helpers/` contains `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`; `test_suite/` contains `conftest.py` plus 18 `test_*.py` files (`test_01_dual_variant_calculations.py` … `test_18_consistency.py`) totalling 114 test functions. The subagent's own summary (coverage audit, design-index tagging, skipped instances) is unrecoverable — its context was discarded when the prior run died. Regenerating would have invalidated the Step 6 implementation built against it.

## Step 6: Generate implementation — 2026-09-02T11:33:00.000Z (artifact recovered on resume)

RESUME NOTE (orchestrator): Step 6 likewise completed in a prior run without a worklog entry, and satisfies resume check #5, so it was NOT regenerated. `workspace/implementation/` contains `start.sh`, `requirements.txt`, `app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `validation.py`, `routes/` (12 modules: assessments, awards, ballots, claims, clock, common, contributions, cycles, matters, partners, transitions) and `services/` (`calculations.py`, `engine.py`). The subagent's own summary is unrecoverable for the same reason as Step 5. No stale `results.*.json` were present, so the Step 7 sweep starts from a clean slate.

## Step 7: Run tests and iterate — 2026-09-02T12:05:00.000Z

Clean sweep achieved: all 8 parallel rounds passed 114/114.

## Summary

**Iterations run:** 3 sweeps (8 parallel rounds each, `per-test-server` isolation).

- Sweep 1: 110/114 in every round — 4 deterministic failures, zero flakiness.
- Sweep 2: 113/114 (one residual missing-import in the same test).
- Sweep 3: **114/114 in all 8 rounds.**

**Tests deleted:** none. All four failures traced to test-artifact bugs or one implementation bug; every asserted rule was verbatim in PRD.

**Fixes applied to `test_suite/`**

- `test_suite/test_17_occ_and_counters.py` — added missing barrel imports `allocate_origination_credit` and `notice_of_departure_payload`; `test_occ_transition_void_after_an_intervening_matter_write` died with `NameError` before issuing a single request (pure import-list bug; `pyflakes` over `test_suite/` + `test_helpers/` now reports no undefined names).
- `test_suite/test_04_transitive_cascades.py` — `test_split_writes_both_rows_and_lifts_the_matter_capacity` asserted `total_formula_score == 0.0000` as a precondition, but the scenario's FORMULA claimant already holds BILLING/RESPONSIBLE/WORKING credit on a matter with 100,010 collected cents, so PRD §3.5 requires a non-zero score (impl returned 42.0417, which recomputes correctly by hand). Replaced with the PRD-derived identity from §3.5 — after the split the cycle total equals the sum of the ACTIVE FORMULA partners' `formula_score_provisional` — which additionally exercises the cascade the docstring cites.
- `test_suite/test_08_temporal_overlap.py` — `test_a_one_day_gap_between_pro_bono_windows_is_too_small` kept its rejection assertion (window starting the day after an existing window's end: rejected under every reading of PRD §3.3) but its follow-up "accepted" window at `end + 2 days` sits exactly on the ambiguous boundary: PRD's "separated by more than one calendar day … or leaves a gap of only one day" admits both `end + 2` (date-difference reading) and `end + 3` (clear-days reading) as the first legal start. Per STEP 1c partial-coverage handling, the boundary assertion was moved off the ambiguous point to `2026-04-05`, which both readings accept.

**Fixes applied to `implementation/`**

- `workspace/implementation/services/engine.py`, `recompute_all()` — the global cascade recomputed `target_award_cents` for *every* award in award state `PROPOSED`, including awards created moments earlier by the `PEER_REVIEW → DELIBERATION` edge. Since a LOCKSTEP award's amount (§3.8) ignores the pools, a freshly created lockstep award immediately showed its gross contractual figure (200,000,000) instead of the `target_award_cents` of 0 that §3.8 mandates at creation, and that stale value also survived a rejected `AWARDS_PUBLISHED` advance, contradicting §2.9 ("a rejected request changes nothing"). The recompute is now gated on `reconsideration_count > 0`, i.e. it applies only to an award that was published and returned to `PROPOSED` by the reopen edge — which is the only situation §3.4's "`target_award_cents` on every award still in award state `PROPOSED`" cascade can be about. Verified against the passing lockstep publication/haircut tests in `test_12_calculations.py`, all of which read post-publication values.

**Orchestrator verification:** independently re-read all 8 `results.$i.json` — every round reports `passed=114 / total=114 / failed=0`.

**Fixes applied to `test_helpers/`:** none.

## Step 8: Finalize PRD — 2026-09-02T12:12:00.000Z

`PRD_FINALIZED.md` is written. Four edits, all traceable to `<step_7_diff>` items.

## Line counts
- `PRD.md`: 487 lines / 14,529 words / 103,457 chars
- `PRD_FINALIZED.md`: 487 lines / 14,743 words / 104,891 chars
- Δ lines: **0 (+0.0%)** — the PRD is one paragraph per line, so edits are inline. Δ words **+214 (+1.47%)**, Δ chars **+1,434 (+1.39%)**.

## Changes
- **§2.9** — revise — the long-cascade tail no longer claims the provisional target award is recomputed for *every* pre-publication award; it now names only awards a reconsideration reopen returned to `PROPOSED` (`reconsideration_count > 0`), and states that a never-yet-published `PROPOSED` award keeps `target_award_cents` of 0 until publication — `implementation/services/engine.py:287`
- **§3.1** — revise — same narrowing on the credit-transition-effectuation cascade tail ("`target_award_cents` on every award still in award state `PROPOSED`") — `implementation/services/engine.py:287`
- **§3.4** — revise — same narrowing on the allocate-decision cascade tail — `implementation/services/engine.py:287`
- **§3.3** — insert — pinned the non-billable service-period buffer boundary: clear-days counting, so a new window is admitted only when its start is ≥3 calendar days after an existing window's end (or its end ≥3 days before that window's start); earliest legal start is the third day after the existing end — `implementation/routes/contributions.py:88,96` (`SERVICE_PERIOD_BUFFER_DAYS = 1` at `implementation/services/calculations.py:10`)
- **§3.5** — insert — pinned that `total_formula_score` is the sum of contributing partners' **`formula_score_provisional`** rounded half up to 4 dp, that the provisional variant feeds it at every cycle stage, and that the §3.8 final award therefore divides `formula_score_final` by that provisional-basis total — `implementation/services/engine.py:261,265` and `implementation/services/calculations.py:347-352`

## Not patched (fixture bugs, PRD already determinate)
- `test_17` missing barrel imports — pure test-artifact bug; no behavior at stake.
- `test_04`'s deleted `total_formula_score == 0.0000` precondition — a wrong fixture assumption; the *replacement* assertion is what revealed the provisional-variant silence, which is the §3.5 edit above.

## Per-edit pre-edit search log

**Edit 1–3 (§2.9 / §3.1 / §3.4 target-award cascade)**
- (a) Subject: every write of `target_award_cents` and every gate on `award_state == PROPOSED` / `reconsideration_count`.
- (b) Enumerated: `grep -rn "target_award_cents\|reconsideration_count" implementation/` → `services/engine.py:283-289` (cascade, gated `PROPOSED && reconsideration_count > 0`); `routes/cycles.py:188` (award created at 0), `:193` (`reconsideration_count` seeded 0), `:214-220` `_publish_awards` (sets target + `draw_schedule_monthly_cents` for **all** cycle awards on the publication edge), `:249` `_reopen` (only incrementer of `reconsideration_count`, also `PUBLISHED → PROPOSED` and `payment_state → PENDING`); `routes/awards.py:94,112` (true-up writes `final_award_cents`, never `target_award_cents`); `services/calculations.py:339-356` `award_amount`.
- (c) Adjustment: initial wording would have said "only reopened awards ever get `target_award_cents` recomputed", which `_publish_awards` contradicts. Re-scoped each sentence to the *cascade* link only (leaving §3.8's publication-edge and §3.9's `PROPOSED → PUBLISHED` prose untouched and still authoritative), and added "until the publication edge assigns it money" so the publication path is not excluded. Deliberately left §3.8's "Only awards in award state `PROPOSED` or `PUBLISHED` are recomputed; a `FINALIZED` award is frozen" verbatim — it is a necessary-condition statement that stays true of both the cascade and the true-up path, and rewriting it risked a new false universal.

**Edit 4 (§3.3 buffer)**
- (a) Subject: the non-billable service-period buffer check.
- (b) Enumerated: `grep -rn "BUFFER\|service_period" implementation/` → sole raiser `routes/contributions.py:85-98` (`gap = SERVICE_PERIOD_BUFFER_DAYS + 2 = 3` days, symmetric `>=` on both sides), sole callsite `:65` (guarded by `kind == "NON_BILLABLE"`), constant `services/calculations.py:10`, code map `errors.py:65`. Also checked the loop's own filters: partner + `NON_BILLABLE` + category, **no** cycle scoping and **no** `verified` filter.
- (c) Adjustment: wrote the boundary symmetrically (both start-after-end and end-before-start) to match the two-sided `>=` test rather than only the forward direction. Left the record-selection predicate (all cycles, verified or not) unstated — it is already consistent with PRD's unscoped "any single pairing of `partner_id` and `category`" and lies outside the Step 7 site.

**Edit 5 (§3.5 total_formula_score)**
- (a) Subject: how the cycle's `total_formula_score` is produced and consumed.
- (b) Enumerated: `grep -rn "total_formula_score" implementation/` → `services/engine.py:253-274` (anchor cycle: sum of `formula_score_provisional` over `ACTIVE`/`NOTICE_GIVEN` `FORMULA` partners, `rhu(...,4)`; **non-anchor cycles forced to `0.0000`**), `routes/cycles.py:58` (seeded `0.0000`), `services/calculations.py:346-352` (`award_amount` FORMULA divides by `cycle["total_formula_score"]` under **both** variants). Also re-read §2.9, §3.1, §3.2 (line 229 already says "the anchor cycle's `total_formula_score`"), §3.4 and §3.8 for consistency.
- (c) Adjustment: dropped an earlier draft that read "the cycle's `total_formula_score` is the sum of …" as an unconditional definition — that would have mis-described non-anchor cycles, which the impl pins to `0.0000`. Kept the existing subject phrase ("the cycle's `total_formula_score`") untouched and attached only the variant-and-rounding pin plus the §3.8 consumption note, leaving anchor-vs-non-anchor scoping under-determined exactly as PRD §2.6/§3.2 already leave it.

## Step 9: Complete PRD — 2026-09-02T12:22:00.000Z

Done. Verified the endpoint surface matches exactly (50 routes) and walked every calculation, state machine, validation order and cascade in `implementation/`.

## Counts
- **Source**: `PRD_FINALIZED.md` — 487 lines, 104,891 bytes
- **Output**: `PRD_COMPLETED.md` — 487 lines, 109,936 bytes (**+5,045 bytes**, 25 in-paragraph line revisions, 0 new sections/paragraphs)
- **Ambiguity-pins**: 20 · **Mismatch-revisions**: 5

## Changes
- **2.3 Pagination** — insert — ambiguity — unrecognised query parameters are ignored rather than rejected — `validation.py:170-198`
- **2.4 Resource Identity** — insert — ambiguity — `created_at`/`updated_at` are stamped from the logical clock, not the host clock; only `api_request_timestamp` uses the host clock — `db.py:66-67,99-102` / `response.py:17-19`
- **2.4 Resource Identity** — insert — ambiguity — `version` rises by at most 1 per request however many times the request touches the row; a row the request created stays at `version` 1 despite the cascade — `db.py:84-107`
- **2.5 Logical Clock** — insert — ambiguity — clock endpoint returns 200 with `data` = `{"current_utc": …}`; missing/unparseable `to_iso8601` is malformed — `routes/clock.py:16-19`
- **2.7 Precision** — insert — ambiguity — an inbound numeric with excess decimals is rounded half up to the declared precision (range checked pre-rounding), not rejected — `validation.py:61-79`
- **2.11 rung 4** — insert — ambiguity — every free-text field carries min length 1, so `""` fails schema whether required or optional — `validation.py:31-43`
- **2.12 Confidentiality** — insert — ambiguity — `CommitteeMember` ballot list: naming a closed cycle in `cycle_id` is refused; without it, closed cycles' ballots are silently omitted — `routes/ballots.py:46-55`
- **3.1 Roster** — revise — mismatch — dropped "and on every later edit of either"; no partner-edit endpoint exists — `routes/partners.py` (no edit route)
- **3.1 Effectuation** — revise — mismatch — `effective_on` baseline falls back to the matter's `opened_on` when no `ACTIVE` originating row remains, and the check runs *after* the state gates and the stale-version guard (so `ERR_STALE_VERSION` wins over the 422) — `routes/transitions.py:78-84`
- **3.1 Departure** — revise — mismatch — `NOTICE_GIVEN → DEPARTED` is re-tested only by effectuate/void, so a partner whose notice staged no transition stays in `NOTICE_GIVEN` forever — `routes/transitions.py:126,172,176-185`
- **3.2 Matters** — insert — ambiguity — `is_first_matter_for_client` is evaluated once at creation and never revisited — `routes/matters.py:33-35`
- **3.3 Buffer** — insert — ambiguity — the service-period buffer spans all of the partner's records in that category, across cycles and regardless of verification — `routes/contributions.py:89-98`
- **3.3 Verification** — insert — ambiguity — when a matter's total verified billable hours are 0 the `WORKING` `credit_pct` recompute is skipped and rows keep their value (a new row therefore 0.00) — `services/engine.py:109-115`
- **3.4 Adjudication** — insert — ambiguity — `decision` literals `ALLOCATE`/`SPLIT`/`REJECT`/`REMAND`; `approved_pct` required on allocate+split, `counterparty_pct` on split only, both 0.00–100.00; `remand_reason` optional even on remand — `routes/claims.py:19,152-162`
- **3.4 Ceiling** — revise — mismatch — only `ACTIVE` *and* `TRANSFERRED` originating rows participate in the 100% interval ceiling (`SUPERSEDED` ignored); the sum is evaluated at each window's `credit_from` — `services/engine.py:53-82`
- **3.5 Formula score** — insert — ambiguity — `total_formula_score`/`total_committee_points` are carried on the anchor cycle alone; every other cycle (including a closed one) reports 0.0000/0.00 — `services/engine.py:253-274`
- **3.6 Peer review** — insert — ambiguity — `outcome` literals `SCORE`/`RECUSE` — `routes/assessments.py:19`
- **3.6 Review decision** — insert — ambiguity — `decision` literals `ACCEPT`/`RETURN` — `routes/assessments.py:18`
- **3.7 Ballots** — insert — ambiguity — ballots materialise subject-major in subjects' then members' `created_at` order (the ordering the trimmed mean and list inherit) — `routes/cycles.py:158-177`
- **3.7 Ballots** — insert — ambiguity — `action` literals `CAST`/`ABSTAIN`/`RECUSE` — `routes/ballots.py:17`
- **3.7 Committee points** — revise — mismatch — `total_committee_points` sums only `DISCRETIONARY` partners in `ACTIVE`/`NOTICE_GIVEN`, rounded to 2 dp, anchor cycle only — `services/engine.py:257-266`
- **3.8 Cycle creation** — revise — mismatch — `undistributed_cash_cents` starts at the full `distributable_pool_cents`, not 0; other pool/total fields enumerated explicitly — `routes/cycles.py:54-63`
- **3.8 Award creation** — insert — ambiguity — awards created in partners' `created_at` order; `final_award_cents`, `true_up_delta_cents`, `capital_call_cents` null while the other counters start at 0 — `routes/cycles.py:179-195`
- **3.9 Draw run** — revise — mismatch — a *fourth* precondition: `payment_state` must still be `PENDING`/`DRAWING` (checked first); plus `period_year` 2000–2100, `period_month` 1–12, and the `memo` is server-composed — `routes/awards.py:57-77`
- **3.9 Capital contribution** — insert — ambiguity — `amount_cents` is an integer of at least 0 — `routes/partners.py:141`

**Pipeline complete.** All 9 steps satisfied; `workspace/PRD_COMPLETED.md` written.
