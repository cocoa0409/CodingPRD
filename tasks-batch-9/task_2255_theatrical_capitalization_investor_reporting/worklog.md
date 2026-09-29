# Worklog — task_2255_theatrical_capitalization_investor_reporting

## Step 1: Create task directory — 2026-09-01T11:00:51.371Z

Created `tasks/task_2255_theatrical_capitalization_investor_reporting/` and `tasks/task_2255_theatrical_capitalization_investor_reporting/workspace/` (directory name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T12:27:23.245Z

All three scaffold artifacts are written and the linter is clean.

**Output files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2255_theatrical_capitalization_investor_reporting/`)
- `SCAFFOLD.yaml` (2,762 lines) — §1.0–§1.7 only, no design keys
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (5,339 lines) — single key `scaffold_difficulty_design` (list of 9 rule groups)
- `SCAFFOLD_CORNER_DESIGN.yaml` (8,087 lines) — single key `scaffold_corner_design` (list of 9 guide sections)

**§1.0–§1.7 surface** — `difficulty_level: "beyond Expert"`; archetypes Ledger reconciliation + Compliance/audit; layers `dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency`; flat topology, parallel state-machine shape, `segregation_of_duties` role model, immediate consistency.
- 15 entities, 13 state machines / 43 transitions (Production carries two parallel axes: `offering_status` and `operating_status`)
- 10 calculations (`wrap_settlement` and `recoupment_progress` are the dual-variant pair; `break_even_analysis` is a circular pool-floor solver), 14 ordered validation priorities, 69 endpoints, 55 errors, 5 roles, 2 OCC rules (both on `expected_production_version`)

**§1.8** — 30 instances across the nine required Difficulty Rules (2–4 each): dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 3, priority_pair_validation_conflict 4, boundary_precision_check 4, cross_entity_state_dependency 4, resource_temporal_overlap 3, compensating_invariant 4.

**§1.9** — 86 instances (68 with full `test_recipe`, 18 `excluded_because` stubs) across all nine guide sections: entities 11, state_machines 16, calculations 11, validations 26, endpoints 5, errors 3, rbac 6, cross_cutting_complexity_layers 7, consistency_model 1.

**Lint verdict (verbatim, final run)**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2255_theatrical_capitalization_investor_reporting/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2255_theatrical_capitalization_investor_reporting/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2255_theatrical_capitalization_investor_reporting/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    69
  §1.1 entities declared:     15
  §1.8 instances scanned:     30
  §1.9 instances scanned:     68
  Calls scanned (§1.8+§1.9):  1643

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Coverage audit**
- All 55 error ids are triggered by at least one §1.8/§1.9 recipe (0 unreachable).
- All 69 endpoints are exercised by at least one call (the last two gaps, `GET /theatres/{id}` and `GET /subsidiary-rights-income`, were closed by extending two corner instances).
- Instance names are unique across §1.8 ∪ §1.9; every stub's cited `difficulty_instance` resolves by name in the §1.8 file.
- Forbidden vocabulary ("simultaneously", "first-writer-wins", "race winner", "in parallel") absent from all three files; no YAML anchors/aliases in either design file.

**Three consistency edits made to `SCAFFOLD.yaml` while §1.9 forced the §1.5/§1.4 audit** (each unblocked an otherwise unreachable corner): priority 14 rewritten to pin sub-order 14a–14e so `ERR_NO_INVESTOR_ACCOUNTS` precedes the cash ceiling; VERSION SEMANTICS added to §1.2.1 so cascade-touching requests increment `version` by exactly 1 (lets corner asserts lock literal versions); priority 9 extended with the `REHEARSAL -> PREVIEWS` active-operating-budget guard plus `POST /productions/{id}/operating-status` in its `applies_to`, making `ERR_ACTIVE_OPERATING_BUDGET_MISSING` reachable.

No sibling `task_*/` directory was read, listed, globbed, or grepped at any point.

## Step 3: Copy shared files — 2026-09-01T12:27:48.816Z

Copied `./INSTRUCTION.md` to `tasks/task_2255_theatrical_capitalization_investor_reporting/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-01T12:42:42.400Z

PRD generated and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2255_theatrical_capitalization_investor_reporting/workspace/PRD.md` — 460 lines. Ends at §5; no audit footer written into the file or any sibling file. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced, and no sibling `task_*/` directory was read.

## Sections written

- **§1 Introduction** — 3 paragraphs (the two-discipline framing, the artifact inventory, and the reversibility/duty-separation commitments).
- **§2** — 12 subsections, domain-derived: 2.1 RBAC, 2.2 API Response Structure (pasted verbatim from the skill's source file), 2.3 Pagination, 2.4 The Logical Production Calendar, 2.5 Money/Points/Percentage Precision, 2.6 Records, Revisions and the Version Counter, 2.7 Optimistic Concurrency on the Production File, 2.8 Cascade Discipline, 2.9 Twin State Axes, 2.10 Flat Addressing and the Order of Validation, 2.11 Fiscal Ceilings and Their Evaluation Order, 2.12 Segregation of Duties and Investor Confidentiality.
- **§3** — 9 subsections (within the 5–9 band), grouped by production lifecycle rather than by entity: houses/engagements/production file; capitalization budget; offering instruments and accreditation; subscriptions and capital accounts; operating calendar and operating budget; royalty participations and pool conversion; the weekly wrap; the recoupment ledger, licensing income and break-even; distributions and closing.
- **§4** — intro paragraph on status codes plus a 4-column table (verified: every row exactly 4 columns).
- **§5** — 2-column table (verified: every row exactly 2 columns).

## Coverage audit (machine-verified against SCAFFOLD.yaml)

| Scaffold element | In scaffold | In PRD | Gap |
|---|---|---|---|
| Entities | 15 | 15 | 0 |
| Entity field identifiers | 119 | 119 | 0 |
| Endpoints (method + path + role list) | 69 | 69 | 0 |
| State machines / transitions | 13 / 43 | 13 / 43 | 0 |
| Calculations | 10 | 10 | 0 |
| Validation rules (priorities 1–14) | 14 | 14 | 0 |
| Concurrency rules | 2 | 2 | 0 |
| Error IDs (+ HTTP status) | 55 | 55 | 0 status mismatches |
| Roles | 5 | 5 | 0 |

Endpoint paths, methods, and per-endpoint authorized-role sets were diffed programmatically against the scaffold: zero mismatches in either direction. Error IDs were diffed with their HTTP statuses: zero missing, zero extra, zero status disagreements. (Note: the scaffold's `complexity_profile` comment says "48 errors" but `errors[]` actually holds 55 — the comment is stale; the PRD follows `errors[]`.)

## Hard Contract reports

```
Field coverage check:
- entities[].fields: 119 required, 119 present, 0 missing
- endpoints[].request_body: all present (expected_production_version, to_status,
  to_iso8601, units, closing_costs_cents, accreditation_status, defect_note,
  withdrawal_reason, dispute_note, void_reason, rescission_reason, ...), 0 missing
- endpoints[].query_params: all present (limit, offset, production_id, theatre_id,
  offering_status, operating_status, recoupment_status, engagement_type, component,
  commitment_status, status, offering_document_id, investor_id, role,
  operating_budget_id, wrap_id, royalty_participant_id, source,
  distribution_type), 0 missing
- endpoints[].output-only identifiers: all present (current_utc,
  investor_account_id, royalty_min_guarantee_floor_cents,
  target_adjusted_gross_cents, break_even_gross_cents,
  capacity_gross_projection_cents, break_even_paid_capacity_pct,
  weeks_to_recoup_at_last_certified_run_rate, cash_basis_recouped_cents,
  cash_basis_recoupment_pct, accrual_basis_recouped_cents,
  accrual_basis_recoupment_pct, subsidiary_rights_receivable_cents), 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 14 checked, 14 expressed in prose (§2.10 ladder + §2.11 fiscal sub-order), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint,
  expected_production_version, ERR_STALE_PRODUCTION_VERSION, 412 all named), 0 missing
- state_machines[].transitions: 43 checked, 43 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed including all 4 variant pairs, 0 missing
- validations[] conditions: 55 error conditions checked, 55 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 112 side-effect entries checked, all expressed
  as cascade descriptions in §2.8 and §3.1–3.9, 0 missing
- entities[].fields[] structured content: allocation_breakdown entry shape
  reconstructible from §3.9; all enum value sets enumerated verbatim, 0 missing
- sibling-branch symmetry: 6 groups checked (FIXED_GROSS vs POOL settlement;
  FIXED_GROSS_SPLIT vs POOL_SPLIT; CASH_BASIS vs ACCRUAL_BASIS; accept vs rescind;
  certify vs void; issue vs withdraw vs settle) — equal prose density in each, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 824
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Zero-Silence / Rule-Coverage notes

"Zero-Silence Rule" is not a term SKILL.md defines; I read it as Hard Contract 2 (a name stated without its rule counts as not stated). Every named field is accompanied by its governing rule. Items that were most at risk of being named-but-silent, and how each was handled:

1. **`weekly_fixed_rent_cents`** is a genuine decoy — it feeds no calculation. Rather than omit it, §3.1 states explicitly that it is recorded for reference and "deliberately, feeds no calculation anywhere in this system."
2. **`min_guarantee_cents`** is named with its narrow scope spelled out: it participates only in the aggregate pool floor and the deferral accrual, and per-participant guarantees are never topped up.
3. **The `ERR_OFFERING_NOT_EFFECTIVE` / `ERR_OFFERING_EXPIRED` split** (priority 9 deferring `EXPIRED` to priority 12) is stated twice — as an ordering note in §2.10 and operationally in §3.3/§3.4.
4. **The 14a–14e fiscal order**, including that `ERR_NO_INVESTOR_ACCOUNTS` is structural and precedes every cash ceiling, has its own subsection (§2.11) plus a restatement in §3.9.
5. **`ERR_MAX_INVESTORS_EXCEEDED` before `ERR_OVERSUBSCRIPTION`** (priority 11 ahead of 14a) is called out explicitly, since the naive ordering is the reverse.
6. **Version semantics** — one increment per row per request regardless of cascade depth — is stated as a named rule in §2.6, framed in stale-version terms only (no "simultaneously", "race", or "first-writer-wins" anywhere; the one incidental "simultaneously" was reworded).
7. **`TheatreEngagement`'s missing `updated_at` and `version`** is stated affirmatively in §2.6 rather than left as an omission.
8. **`recoupment_pct` can round to 1.0000 while `recoupment_status` still reads `UNRECOUPED`** — the rounding-vs-threshold subtlety is preserved in §3.8.
9. **Pinned rounding order** (round each row first, then push the signed residue onto one designated row) is stated in §2.5 as a global principle and then re-derived per calculation for the three allocations, each with its tie-break and its residue recipient, plus the explicit warning that summing exact fractions and rounding once is not the specified order.
10. **The break-even circularity** is expressed as the seed / walk-down / walk-up procedure with its monotonicity justification and the 100-step bound, without pseudocode.

One judgement call worth flagging: the scaffold specifies the engagement-collision rule only as "the buffered closed-interval rule," so §3.1 pins it precisely — widen the existing inclusive span by `changeover_buffer_days` at each end and reject on any touch — and gives the equivalent dark-day formulation plus a worked boundary case, so an implementer cannot read it two ways.

## Step 5: Generate unit tests — 2026-09-01T14:10:27.244Z

Generation is complete. Final state of the task's test infrastructure and suite:

## Files written

**`test_helpers/`** (9 modules, all under `/home/ubuntu/github/CodingPRD/tasks/task_2255_theatrical_capitalization_investor_reporting/test_helpers/`): `__init__.py`, `api_client.py` (69 endpoints), `api_errors.py` (55 error ids + HTTP status map), `assertions.py`, `constants.py`, `factories.py`, `fixtures.py` (layered world builders `base_world` → `capitalized_world` → `running_world` → `certified_week_world` → `ledger_world`), `test_users.py`, `types.py`. `test_suite/conftest.py` provides the `api` fixture. Final touch this session: `test_helpers/__init__.py`'s `__all__` was completed to the full 101-name public surface (pyflakes is now clean across both packages).

**`test_suite/`** — 18 modules, 128 tests:
- Queue A (depth, `test_01`–`test_10`): 60 tests
- Queue B (breadth, `test_11`–`test_18`): 68 tests — `test_11` entities 11, `test_12` state_machines 14, `test_13` calculations 7, `test_14` validations 18, `test_15` endpoints 5, `test_16` errors 3, `test_17` rbac 6, `test_18` cross-cutting + consistency 4.

## Instances translated vs skipped
- **Difficulty index:** all 30 non-stub instances translated (2 tests each = 60).
- **Corner index:** all 68 non-stub instances translated, one test each.
- **Skipped: none.** No instance failed the PRD-first two-condition filter. The 18 `STUB:` corner entries were correctly not translated (2 state_machines, 4 calculations, 8 validations, 4 cross_cutting).

## Audits run (all pass)
- Collection: `PYTHONPATH=. python -m pytest test_suite --collect-only -q` → **128 tests collected**, no import/collection errors.
- `Design:` tags: every test has exactly one, it is the final docstring line, and all 128 resolve to real non-stub instance names in the two yamls (60 `Difficulty/...`, 68 `Corner/...`). No stub tags, no unknown tags, no non-stub instance left untagged.
- PRD citations: 142 quoted passages extracted from docstrings, every one a whitespace-normalized verbatim substring of `workspace/PRD.md`; every test carries at least one quote.
- Scaffold hygiene: zero occurrences of "scaffold", zero `§` references, and no design-document vocabulary anywhere in `test_suite/` or `test_helpers/`.
- Reference resolution: every `api.*`, `factories.*`, `fixtures.*` and `ApiErrorId.*` symbol used in the new modules resolves against the helpers.

## Coverage notes / deliberate deviations (PRD preferred over design)
- Where a design instance asserted a literal production `version` that depends on whether *paying* a distribution rewrites the production row (not PRD-derivable), the version literal was replaced by `assert_no_write` snapshots plus the state assertion (`test_16` repeat-actions test; earlier `test_10`).
- The design's `engagement_type: LOAD_IN` probe was retargeted to the declared member `REHEARSAL`, since an undeclared enum member would be refused at validation step 4 rather than reaching the body-FK 404 the instance is about (`test_15`).
- `test_13`'s configured-subsidiary-share instance uses `capitalized_world(..., subsidiary_rights_investor_share_pct=0.25)` and a relative version assertion, because `ledger_world` passes that keyword explicitly.
- No test execution was possible (no implementation present in the workspace, and reading `workspace/implementation/` is out of scope), so the suite is verified statically: collection, tag audit, citation grep, symbol resolution, and hand-checked arithmetic against the PRD's documented procedures (standard week: capacity 191,040,000; adjusted gross 61,750,000; royalty base 28,250,000; pct 0.2354).

## Step 6: Generate implementation — 2026-09-01T14:10:27.244Z

Implementation complete and verified.

## Files written

Root: `/home/ubuntu/github/CodingPRD/tasks/task_2255_theatrical_capitalization_investor_reporting/workspace/implementation/`

- `start.sh` — guarded `pip install` (only if Flask missing), then `exec python3 app.py`; `PORT` env var, default 10000, bind `0.0.0.0`.
- `app.py` — 16 blueprints registered in PRD §4 order, `strict_slashes=False`, envelope-shaped 404/405/ApiError/500 handlers.
- `db.py` — in-memory `store` (15 dicts, empty at boot, no seeding/persistence), `_seq` insertion order, logical UTC clock pinned at `2026-08-01T00:00:00Z`, Decimal/ROUND_HALF_UP helpers, `RequestContext` (watch/force/created/commit) implementing "one request bumps each written row's version by exactly 1".
- `response.py`, `validation.py`, `middleware.py`, `errors.py` (all 57 error IDs + HTTP map).
- `services/queries.py`, `services/ledger.py` — all 10 calculations.
- `routes/`: theatres, productions, engagements, budget_lines, operating_budgets, offering_documents, investors, subscriptions, investor_accounts, royalty_participants, weekly_wraps, royalty_allocations, subsidiary_rights, distributions, closing_notices, clock.

3027 lines total, **69 endpoints** (matches the scaffold exactly).

## Verification

Three end-to-end smoke suites re-run on fresh servers after the final edits. Spec-exact numbers confirmed: FIXED_GROSS pool 34200 (22800/11400 on adjusted_gross 570000), POOL split residue 93334/93333/93333, pool-share residue 0.3334/0.3333/0.3333, deferral on a losing week (pool 0, deferred 150000), void unwinding (allocations REVERSED v2, cumulative 0, RECOUPED→UNRECOUPED), rescind unwinding (FULLY_SUBSCRIBED→OFFERING, capital 0), reserve settlement (200000 balance − 50000 costs → 150000 released), lazy `EFFECTIVE→EXPIRED` sweep with version bump on read. Error coverage exercised live across all priority tiers (401/403/404/405/409/412/422), including `ERR_STALE_PRODUCTION_VERSION`, `ERR_OVERSUBSCRIPTION`, `ERR_MAX_INVESTORS_EXCEEDED`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_OPERATING_BUDGET_CHANGED`, `ERR_DISTRIBUTION_EXCEEDS_DISTRIBUTABLE`, `ERR_NOT_YET_RECOUPED`, `ERR_NO_INVESTOR_ACCOUNTS`, `ERR_UNCERTIFIED_WRAPS_EXIST`. All stray test servers killed.

One real bug found and fixed during verification: a duplicate closing notice returned `ERR_INVALID_OPERATING_STATE` instead of `ERR_CLOSING_NOTICE_ALREADY_ISSUED`, since posting the first notice always moves the production to `CLOSING_NOTICE`. Now returns 409 `ERR_CLOSING_NOTICE_ALREADY_ISSUED`.

## PRD ambiguities resolved

1. Committing a budget line while `budget_status != APPROVED` → `ERR_INVALID_BUDGET_LINE_STATE` (409).
2. Voiding a wrap while `operating_status == CLOSED` → `ERR_PRODUCTION_NOT_PERFORMING` (409).
3. Resubmit/subscribe against an EXPIRED document → `ERR_OFFERING_EXPIRED` (422); `ERR_OFFERING_NOT_EFFECTIVE` reserved for DRAFT/WITHDRAWN.
4. `closing-notices/{id}/withdraw` operating-axis guard → `ERR_INVALID_OPERATING_STATE` (409).
5. Closing-notice creation evaluates `ERR_CLOSING_NOTICE_ALREADY_ISSUED` **first**, ahead of the operating-status and temporal rules (otherwise unreachable).
6. `recoupment_credited_cents` refreshed on every recoupment recompute, not only at threshold crossing.
7. Wall clock for `created_at`/`updated_at`/`api_request_timestamp`; logical clock strictly for date comparisons.
8. Free-text reason/note fields validated for presence only (no min length).
9. Closing notice initialises `closing_costs_cents = null` and the three reserve figures to 0 pre-settlement.
10. New `InvestorAccount.basis` seeded from the production's current `recoupment_status` (`NET_PROFIT` if already RECOUPED, else `RECOUPMENT_RETURN`).
11. `investor-distributions/{id}/pay` does not bump `Production.version` (only the distribution and touched accounts), per the scaffold's stated side effects.

## Step 7: Run tests and iterate — 2026-09-01T14:24:04.182Z

Clean sweep: all 8 parallel rounds passed 128/128.

## Summary

**Iterations run:** 2

**Iteration 1** — 8/8 rounds each reported 126/128. The union of failures was exactly 2 tests, failing deterministically in every round (no flakiness surfaced anywhere in the 8-round sweep):
- `test_14_validation_rules.py::TestClosingNoticeRules::test_exactly_the_minimum_notice_is_long_enough`
- `test_18_cross_cutting_layers.py::TestRefusedCascadeAtomicity::test_the_refused_settlement_leaves_the_reserve_line_and_notice_untouched`

Both tripped on the same class of assertion: that an unsettled `ClosingNotice` reads `reserve_released_cents is None` (and, in test_18, `closing_cost_shortfall_cents is None`).

**Diagnosis (STEP 1b — COMPUTED-FIELD SILENCE, non-derivable):** PRD §3.9 makes exactly one null-read commitment on a closing notice — "The comptroller supplies the actual `closing_costs_cents`, at least 0; **that field** reads null on any notice not yet settled". `reserve_released_cents` and `closing_cost_shortfall_cents` appear in PRD only inside settlement-time formulas ("`reserve_released_cents` is the reserve balance less `closing_costs_cents`, floored at 0"), never as pre-settlement response attributes. Two PRD-faithful readings exist: initialise the derived cents fields to 0 (what the implementation does, consistent with §3.8's "Income is filed in `RECORDED` status with `investor_share_cents` at 0" precedent), or leave them null. PRD does not choose. Grep of every "null" sentence in PRD.md confirms coverage only for `withdrawal_reason`, `defect_note`, `rescission_reason`, `dispute_note`, `void_reason`, `closing_costs_cents`, and `weeks_to_recoup_at_last_certified_run_rate`.

**Tests deleted:** none. Both failing tests carry PRD-covered, uniquely-derivable headline rules (the exactly-14-days notice period is admissible and cascades; a settlement refused by `ERR_UNCERTIFIED_WRAPS_EXIST` writes no partial cascade), so the tests were kept and only the non-derivable assertion lines were removed under STEP 2.

**Fixes applied to `test_suite/`:**
- `test_suite/test_14_validation_rules.py` — `TestClosingNoticeRules::test_exactly_the_minimum_notice_is_long_enough`: dropped `assert notice["reserve_released_cents"] is None`; PRD's null-read sentence covers `closing_costs_cents` only. The PRD-traceable assertions (`notice_days == 14`, `status == "ISSUED"`, `closing_costs_cents is None`, `settled_by_user_id is None`, axis moved to `CLOSING_NOTICE`, reserve line `COMMITTED`, `budget_committed_cents`, `version == 9`) all retained.
- `test_suite/test_18_cross_cutting_layers.py` — `TestRefusedCascadeAtomicity::test_the_refused_settlement_leaves_the_reserve_line_and_notice_untouched`: dropped `assert notice["reserve_released_cents"] is None` and `assert notice["closing_cost_shortfall_cents"] is None`, same reason. The no-partial-cascade claim is still fully proved by the retained assertions: reserve line still `COMMITTED` at `version == 2`, notice still `ISSUED` with `closing_costs_cents`/`settled_by_user_id` null, `operating_status == "CLOSING_NOTICE"`, `budget_committed_cents == 20_000_000`, `recouped_amount_cents == 0`, production `version == 9`.

**Fixes applied to `test_helpers/`:** none — no fixture, factory or role-header bug surfaced.

**Fixes applied to `implementation/`:** none. No PRD-required check was removed or weakened, no assertion was downgraded to an HTTP-status check, and no skip/xfail was added anywhere.

**Iteration 2** — 8/8 parallel rounds passed 128/128 (~170 s per round). No test passed in some rounds and failed in others at any point, so no timing-sensitive defect was masked.

## Step 8: Finalize PRD — 2026-09-01T14:26:11.280Z

Done. `PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_2255_theatrical_capitalization_investor_reporting/workspace/PRD_FINALIZED.md`.

## Line counts
- PRD.md: 459 lines; PRD_FINALIZED.md: 459 lines. Delta: 0 lines (0.0%); one existing line (§3.9, line 321) extended by a single sentence — the only change in the file.

## Changes
- **§3.9 (closing-notice reserve settlement) — insert — pinned the pre-settlement read values of the three derived reserve cents fields (`reserve_balance_at_settlement_cents`, `reserve_released_cents`, `closing_cost_shortfall_cents`) as 0 rather than null, explicitly contrasting them with `closing_costs_cents`, and covered the `WITHDRAWN`-without-settlement case — `implementation/routes/closing_notices.py:77-79`.**

## Pre-edit search log (single edit)
**(a) Subject.** The value read on a `ClosingNotice`'s derived reserve cents fields before/without settlement — i.e. whether `reserve_balance_at_settlement_cents`, `reserve_released_cents`, `closing_cost_shortfall_cents` are 0-initialised or null. This is exactly the Step 7 Iteration-1 finding (both failing tests asserted `is None` on these fields).

**(b) Impl paths enumerated** (grepped `reserve_released_cents|closing_cost_shortfall_cents|reserve_balance_at_settlement_cents` across all `*.py`, then read each hit in context):
1. `routes/closing_notices.py:70-90` — `create_closing_notice` insert: `closing_costs_cents: None`, `settled_by_user_id: None`, `withdrawal_reason: None`, but `reserve_balance_at_settlement_cents: 0`, `reserve_released_cents: 0`, `closing_cost_shortfall_cents: 0`. Confirms the 0-initialisation and that it is deliberately asymmetric with `closing_costs_cents`.
2. `routes/closing_notices.py:93-115` — `withdraw_closing_notice`: writes only `status` and `withdrawal_reason`; the three cents fields are never touched, so a `WITHDRAWN` notice retains 0. This is a path Step 7 never exercised and is why the sentence names the withdrawn case explicitly instead of saying only "not yet settled".
3. `routes/closing_notices.py:118-155` + `services/ledger.py:319-328` (`closing_reserve_settlement`) — settlement overwrites all three via `notice.update(settlement)`; balance read before reserve lines move `COMMITTED → SPENT`. Both `max(0, ...)` forms mean a settlement where costs exactly equal the balance leaves both figures at 0, so wording avoided any claim that a settled notice has a positive figure (the pre-existing "exactly one of the two figures can be positive" sentence was left verbatim).
4. `services/ledger.py:223-233` (`cash_basis`) — sums `reserve_released_cents` only over notices whose `status` is `SETTLED`, so the 0-init on `ISSUED`/`WITHDRAWN` notices cannot leak into `recouped_amount_cents`; the new sentence is phrased purely as a read-value statement and makes no ledger-input claim, keeping §3.8 consistent.
5. `db.insert` / `db.serialize` / `response.obj` (`db.py:92-101`, `response.py`) — no per-entity field whitelist; only `_`-prefixed keys are stripped, so all three fields are genuinely present in the notice payload for `ISSUED` and `WITHDRAWN` notices. Confirms "reads 0" is observable, not just internal.

**(c) Wording adjustment.** Two: (i) widened from the two fields the Step 7 tests touched to all three fields written by the same settlement dict, because pinning only two would create a false contrast implying `reserve_balance_at_settlement_cents` is null; (ii) added the `WITHDRAWN`-without-settlement clause after reading the withdraw path, since "not yet settled" alone could be read as excluding terminal-but-unsettled notices.

No other PRD edits: the Step 7 diff reports no test deletions and no `implementation/` or `test_helpers/` fixes, and Iteration 2 was 128/128 across 8 rounds, so no further PRD silence or mismatch is in scope.

## Step 9: Complete PRD — 2026-09-01T14:34:25.562Z

All edits applied cleanly.

## Summary

**Files:** `/home/ubuntu/github/CodingPRD/tasks/task_2255_theatrical_capitalization_investor_reporting/workspace/PRD_FINALIZED.md` (459 lines, 95,322 chars) → `.../workspace/PRD_COMPLETED.md` (459 lines, 100,378 chars). **Char delta: +5,056.** 24 lines revised in place; no sections, paragraphs, or lines added or removed.

**Counts: 20 ambiguity-pins, 4 mismatch-revisions.**

- §2.1 — revise — ambiguity — an empty-string `X-User-ID`/`X-User-Role` is treated like an absent one (`ERR_UNAUTHENTICATED`) — `implementation/middleware.py:41`
- §2.3 — revise — ambiguity — a non-integer `limit`/`offset` is also `ERR_INVALID_REQUEST` — `implementation/validation.py:161`
- §2.3 — revise — ambiguity — `created_at` ties in list order are broken by insertion order — `implementation/db.py:111`
- §2.3 — revise — ambiguity — filters are conjunctive exact-match; enum filters 400 on undeclared values, identifier filters are unchecked and yield an empty page rather than 404 — `implementation/validation.py:172`, `implementation/routes/productions.py:89`
- §2.4 — revise — ambiguity — `to_iso8601` parsing (offset converted to UTC, naive read as UTC, unparseable → 400) and the clock response's single `current_utc` field/format — `implementation/routes/clock.py:20`
- §2.6 — revise — ambiguity — a cascade hop that re-derives a swept row to values it already held is not a write (no `version`/`updated_at` move), while the production file, offering document and investor row always advance by 1 on the writes that name them — `implementation/db.py:152`
- §2.10 step 4 — revise — ambiguity — a body field supplied as `null` counts as absent — `implementation/validation.py:30`
- §2.10 step 5 — revise — ambiguity — body foreign keys resolve in the listed order when a body carries more than one — `implementation/routes/subscriptions.py:53`
- §2.10 step 13 — revise — **mismatch** — closing-notice posting is the one write where the uniqueness check precedes its own-state guard (step 8) and the temporal rules (step 12) — `implementation/routes/closing_notices.py:53`
- §3.1 — revise — **mismatch** — the changeover-buffer worked example said the 10th/14th pair "collide" and then called it acceptable; corrected to "do not collide" — `implementation/routes/engagements.py:36`
- §3.1 — revise — ambiguity — `reserve_target_cents` feeds no calculation; `closing_notice_min_days` must be at least 0 — `implementation/routes/productions.py:39`
- §3.2 — revise — ambiguity — budget approval has no state gate (re-approval admissible, still bumps `version`); the line's own commitment status is tested first and an unapproved budget also reports `ERR_INVALID_BUDGET_LINE_STATE` — `implementation/routes/productions.py:170`, `implementation/routes/budget_lines.py:62`
- §3.3 — revise — ambiguity — `contact_email` is stored as supplied with no format check — `implementation/routes/investors.py:23`
- §3.4 — revise — ambiguity — `units` is required (min 1) on resubmission, not optional — `implementation/routes/subscriptions.py:108`
- §3.5 — revise — ambiguity — the cross-axis guard leaving `PRE_PRODUCTION` reports `ERR_PRODUCTION_NOT_CAPITALIZED` (409) — `implementation/routes/productions.py:140`
- §3.6 — revise — ambiguity — `fixed_gross_pct`, `pool_points` and `min_guarantee_cents` are all required with no defaults — `implementation/routes/royalty_participants.py:34`
- §3.7 — revise — ambiguity — at open, `royalty_basis_applied` is null and `royalty_pool_cents`, `weekly_operating_profit_cents`, `deferred_royalty_added_cents` are 0 — `implementation/routes/weekly_wraps.py:96`
- §3.7 — revise — ambiguity — voiding a `CLOSED` production's wrap reports `ERR_PRODUCTION_NOT_PERFORMING` (after the wrap's own state), and void leaves the wrap's settled figures and `certified_by_user_id` intact — `implementation/routes/weekly_wraps.py:226`
- §3.8 — revise — ambiguity — each break-even walk is hard-bounded at one hundred steps — `implementation/services/ledger.py:332`
- §3.9 — revise — ambiguity — paying a distribution writes only the distribution and named capital accounts; the production's `version` does not move — `implementation/routes/distributions.py:85`
- §3.9 — revise — **mismatch** — notice posting now states four rules in impl order (single-notice → operating axis with `ERR_INVALID_OPERATING_STATE` → `notice_date` → notice period) — `implementation/routes/closing_notices.py:53`
- §3.9 — revise — ambiguity — withdrawal off `CLOSING_NOTICE` reports `ERR_INVALID_OPERATING_STATE`, checked after the notice's own state — `implementation/routes/closing_notices.py:104`
- §3.9 — revise — ambiguity — settlement's operating-status precondition reports `ERR_INVALID_OPERATING_STATE` — `implementation/routes/closing_notices.py:133`
- §4 — revise — **mismatch** — unrouted paths and undeclared methods return `ERR_INVALID_REQUEST` at HTTP 404/405, not the catalogue's 400 — `implementation/app.py:47`

Key notes: the implementation matched the PRD on every calculation formula, rounding/reconciliation order, cascade depth, compensating-action conservation, fiscal-ceiling order, endpoint path, and RBAC row in the §4 table — no changes were needed there. The four genuine mismatches were the closing-notice validation ordering, the self-contradictory changeover-buffer example, and the two HTTP-status/route-level facts.
