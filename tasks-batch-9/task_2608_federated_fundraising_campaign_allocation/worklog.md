# Worklog — task_2608_federated_fundraising_campaign_allocation

## Step 1: Create task directory — 2026-09-03T19:09:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2608_federated_fundraising_campaign_allocation` and its `workspace/` subdirectory. Index 2608 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate Scaffold — 2026-09-03T20:50:00.000Z

All three scaffold artifacts are complete and the lint is clean on the first run.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2608_federated_fundraising_campaign_allocation/`

| file | lines |
|---|---|
| `SCAFFOLD.yaml` | 2905 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2115 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3518 |

Top-level keys verified: `SCAFFOLD.yaml` carries only §1.0–§1.7 keys (no `scaffold_difficulty_design`, no `scaffold_corner_design`); the two design files each have exactly one top-level key.

## Scaffold surface (§1.0–§1.7)

`api_prefix: /fundraising`, logical clock default `2026-08-01T00:00:00Z`, consistency `immediate`, topology `graph`, state-machine shape `parallel`, role model `segregation_of_duties`, complexity layers `dual_variant_calculation / cascading_side_effects / optimistic_concurrency / rate_threshold_triggers`.

- **13 entities** (Employer, CampaignCoordinator, Campaign, Pledge, PledgeDesignation, Agency, AgencyReview, Panelist, AllocationCycle, PanelAssignment, AllocationRequest, PanelScore, OutcomeReport)
- **10 state machines**, **2 concurrency rules** (`designation-amend-stale-pledge`, `award-create-stale-cycle`)
- **6 calculations** (2 dual-variant: `agency_financial_standing_score`, `campaign_pledge_loss_estimate`)
- **46 validations** (single strict priority ladder), **55 endpoints** (21 GET + 33 mutations + `POST /_clock/set_current_utc`), **53 errors**, **6 roles**

## Design files

- §1.8: **18 instances** — 9 §0.5 rule_ids × 2.
- §1.9: **71 instances** across the guide's nine sections — 49 with full `test_recipe`, 22 `excluded_because` stubs. Per section: entities 11, state_machines 17, calculations 11, validations 10, endpoints 5, errors 7, rbac 4, complexity_layers 5, consistency_model 1.
- All 89 instance `name`s unique across both files; every stub's cited `difficulty_instance` exists by name in the difficulty file and carries no `test_recipe`.
- **All 53 §1.6 errors are triggerable** somewhere across the two files (verified programmatically).

Lint verdict (verbatim):

```
Coverage
  §1.5 endpoints declared:    55
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     49
  Calls scanned (§1.8+§1.9):  902

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Design adjudications

1. **`partnership_signed: true` vs `/activate`** — `Employer.status` is ACTIVE at creation when `partnership_signed` is true, so 11 §1.8 setup payloads would have made the following `/activate` return `ERR_EMPLOYER_INVALID_STATE` (and one contradicted its own "left in PROSPECT" prose). All 11 keys removed from `SCAFFOLD_DIFFICULTY_DESIGN.yaml`; the corner instance `activate_employer_action_endpoint_rejects_second_activation_with_invalid_state` now tests that short-circuit deliberately.
2. **`ERR_NO_ELIGIBLE_SCORES` reachability** — resolved by verification, not edit: priority 20 already admits a still-`SUBMITTED` request into finalize-review precisely so priority 36 can refuse it. Exercised by `finalize_review_empty_then_sub_quorum_eligible_set_errors_in_priority_order` (empty → `ERR_NO_ELIGIBLE_SCORES`, then 2 eligible scores → `ERR_PANEL_QUORUM_NOT_MET`).
3. **`ERR_AWARD_ALREADY_REPORTED`** — likewise reachable only because priority 20 lets a `REPORTING` request past for priority 41 to refuse; left as declared.
4. **`ERR_POOL_INSUFFICIENT` literals corrected** — the guard is on `total_award_unclamped`, and `base_award` is itself pool-clamped, so the refusal needs the step-5 supplement to break the ceiling: pool 1000.00 / cap 2000.00 / ask 2000.00 / composite 81.50 → step2 1630.00, base 1000.00, offset 0.00, supplement 60.00, unclamped 1060.00 > 1000.00.
5. **`MIN_LINE_FEE` 1.50 is unreachable** — `MIN_DESIGNATION_AMOUNT` 25.00 makes the smallest possible line fee 1.81; noted in the fee-calculation corner instance rather than "tested".
6. **`Agency.ein` global uniqueness has no declared error id** — the corner instance asserts the ein is still free after refused calls without naming a nonexistent `ERR_DUPLICATE_EIN`.
7. Two lint-shaped fixes made while writing: an array-output capture (`$.data.total_count` on `GET /pledges`) was dropped in favour of prose asserts, and `Bulk action` (Table 5) was skipped as non-applicable — no bulk endpoint is declared.

Every money/score literal was computed with `Decimal` + `ROUND_HALF_UP` (e.g. fee totals 11.96 / 18.13 / 21.75, collection scaling 69.56 → 278.25, composite 81.50 and trimmed 77.17, awards 34556.00 / 67156.00, pool 165444.00 / 232844.00, variance 4.23, due date 2027-01-28, shrinkage fork 1495 vs exactly 1500 bps). No sibling task directory was listed, read, or grepped.

## Step 3: Copy Shared Files — 2026-09-03T20:50:30.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T21:10:00.000Z

PRD generated and verified.

**Output:** `workspace/PRD.md` — **455 lines**, ends at the last row of the §5 table (`ERR_POOL_INSUFFICIENT` | 422), no audit footer.

Orchestrator truncation check (per pipeline instructions): `wc -l` = 455; `tail -20` ends on a complete table row at a real section boundary; all five top-level sections (1 Introduction, 2 Global Specifications, 3 Business Logic, 4 Endpoint Definitions, 5 Error Code Catalogue) and all 25 subsections present. NOT truncated — no regeneration needed.

**Section list**
- `# Federated Fundraising Campaign Allocation API — Product Requirements Document`
- `## 1. Introduction` (3 paragraphs)
- `## 2. Global Specifications & System-Wide Principles` — 11 subsections: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (verbatim block) · 2.3 Pagination, Sorting and List Filters · 2.4 Resource Identity, Audit Fields and Version Semantics · 2.5 Money, Ratios and Rounding Discipline · 2.6 Stale-Version Protection on Shared Parents · 2.7 The Logical Clock and Date-Window Conventions · 2.8 Cascade Propagation and Aggregate Re-derivation · 2.9 Left-to-Right Path Resolution and Nested Integrity · 2.10 Order of Evaluation (46-step ladder) · 2.11 Segregation of Duties Across Fund Stewardship
- `## 3. Business Logic & Workflows` — 9 subsections: 3.1 Workplace Partnerships and the Coordinator Roster · 3.2 The Annual Campaign: Solicitation Windows and Posture · 3.3 Recording Pledges and Honoring Donor Designations · 3.4 When the Donor Changes Their Mind: Amending a Designation Line Set · 3.5 Remittance, Write-Offs and Shrinkage Accounting · 3.6 Agency Membership Standards and Financial Review · 3.7 Allocation Cycles, Volunteer Panels and Composite Scoring · 3.8 Awarding the Community Impact Fund · 3.9 Outcome Reporting, Monitoring Site Visits and Closure
- `## 4. Endpoint Definitions` (intro paragraph on 201-vs-200 + 4-column table, all **55** endpoints: 21 GET, 34 POST)
- `## 5. Error Code Catalogue` (2-column table, all **53** error ids)

**Contract 1 — Field-Name Coverage: PASS.** All 141 `entities[].fields[].name` across 13 entities appear verbatim in backticks; all 85 endpoint `input` / `path_params` / structured-output identifiers appear in backticks (including every optional query param and `to_iso8601`, `expected_pledge_version`, `expected_allocation_cycle_version`, `review_id`). Two passes: pass 1 found `membership_status` and `review_id` unbackticked in prose — both fixed (§3.6 agency creation; §2.9 nested integrity); pass 2 clean. Every enum value of every enum field also appears.

**Contract 2 — Rule Coverage: PASS.** All 46 `validations` appear as the §2.10 numbered ladder in exact priority order, each with its error id (priorities 4 and 5 delegate to §2.9, which enumerates all nine 404 codes in path order). All 53 error ids appear in prose outside §4/§5. Both `concurrency_rules` (OCC on `Pledge` and on `AllocationCycle`, with the reason each is not caught by a state precondition) are in §2.6. All 10 state machines: every initial state, terminal state and all 50 transitions are spelled as explicit `FROM → TO` pairs (pass 1 found 10 transitions described in prose but without arrow notation — `CONFIRMED|AMENDED → LOCKED`, `PENDING|PARTIAL → WRITTEN_OFF`, `ACTIVE → SUPERSEDED`, `ACTIVE → UNCOLLECTED`, `APPLICANT|GOOD_STANDING → UNDER_FINANCIAL_REVIEW`, `SUBMITTED|UNDER_PANEL_REVIEW → SUSPENDED_REVIEW`; all rewritten to arrow form). All 6 calculations reconstructible step-for-step with pinned evaluation order and worked examples (fee allocation 7.25%/1.50 floor; both loss variants; both standing-score variants; trimmed-mean composite; 7-step award waterfall; expenditure variance). All three cascades with their link counts and their reversals in §2.8 and in §3.5/§3.6/§3.8. Sibling-branch symmetry held for all forks (reconcile, membership bands, finalize-review, revision vs acceptance). Field-level structured content: the `designations` array element shape `{ agency_id, designated_amount }` is spelled at both creation and amend.

**Contract 3 — §3 Path Purity: PASS.** Zero backticked tokens in §3 (lines 191–336) start with `/`, are a bare HTTP method, or combine method+path. §3 refers to operations by capability name only. (`/fundraising` appears once, in §1, as the API prefix.)

**Adjudications** (scaffold self-contradictions; PRD follows the resolution shown):
1. **Reconcile fork boundary** — endpoint side-effect text says `RECONCILED` when `realized_shrinkage_rate_bps <= threshold`, else `ESCROW_HOLD`; the calculation and both transitions pin `>= 1500 → ESCROW_HOLD`. Resolved to the formula/transitions: `>= 1500` (1500 inclusive) → `ESCROW_HOLD`, strictly `< 1500` → `RECONCILED`.
2. **Reinstate actor** — state machine names `FinanceReviewer`; endpoint `roles` and the RBAC matrix name `UnitedFundAdmin` and `AllocationsDirector`. Resolved to endpoint roles + RBAC matrix (which is also consistent with §2.11 segregation of duties).
3. **`Agency.latest_standing_score` initial value** — entity default `null` ("null when no review is CERTIFIED") vs agency-creation side effect "initialises … to 0". Resolved to `null`.
4. **Review filing from `PROBATION`** — endpoint admits `APPLICANT|GOOD_STANDING|PROBATION → UNDER_FINANCIAL_REVIEW` while the state machine defines entry hops only from the first two and separately defines `PROBATION → PROBATION` / `PROBATION → SUSPENDED_MEMBERSHIP` certify transitions. Both expressed: filing moves from all three, and an agency still on `PROBATION` at certify time follows the same bands from that starting point, re-running cascade links 3 and 4.
5. **Permissive status admissions** — priority 20 admits a still-`SUBMITTED` request into finalize-review (then fails priority 36 `ERR_NO_ELIGIBLE_SCORES`) and a `REPORTING` request into rescind-award (then fails priority 41 `ERR_AWARD_ALREADY_REPORTED`), though the transitions start only from `UNDER_PANEL_REVIEW` / `AWARDED`. Both admissions are stated explicitly so the implementer produces 422 rather than 409.
6. **Pledge confirm side effects** — endpoint adds "recomputes `Agency.designated_passthrough_ytd`", absent from the transition. Included as a superset.
7. **Outcome-report resubmit and the site-visit fields** — the state-machine transition says it "clears `site_visit_findings` but KEEPS `site_visit_panelist_id`, `site_visit_window_start` and `site_visit_window_end` so the buffer rule still sees the historic window"; the endpoint side-effect list says it clears all four. Resolved to the state machine (clear findings only, keep panelist id and window) because it is the more specific statement and supplies the design reason.

## Step 6: Generate Implementation — 2026-09-03T21:40:00.000Z

Orchestrator note on launch order: Steps 5 and 6 were launched as two background Agent calls issued back-to-back (Step 5 first, then Step 6 immediately after, before any other work). Both ran concurrently. Physical isolation of the impl generator from `test_suite/` was additionally enforced by an explicit hard constraint in the Step 6 prompt forbidding any read/list/glob/grep of `test_helpers/` or `test_suite/`.

Implementation complete and verified.

## Modules (`workspace/implementation/`, 3131 lines total)

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 10 | guarded `pip install` + `exec python3 app.py` (executable) |
| `requirements.txt` | 1 | `Flask>=2.2` |
| `app.py` | 83 | blueprint registration (`/fundraising` + bare `/_clock`), envelope error handlers, `PORT`/`0.0.0.0` |
| `errors.py` | 78 | 54-entry error→HTTP status catalogue, `ApiError` |
| `store.py` | 155 | in-memory dicts, logical clock (default `2026-08-01T00:00:00Z`), Decimal quantizers, `base_entity`/`touch` |
| `envelope.py` | 134 | `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` pagination, filters |
| `validators.py` | 190 | gate-3 shape validation, `json.loads(parse_float=Decimal)` |
| `auth.py` | 110 | `X-User-ID`/`X-User-Role`, 6 roles, entity-backed identity + ownership |
| `services/calc.py` | 298 | all 8 calculation families + every domain constant |
| `services/aggregates.py` | 336 | every computed/derived field re-derivation + the 3 cascades' shared links |
| `routes/employers.py` | 120 | employers + coordinators |
| `routes/campaigns.py` | 178 | campaign posture, provisional/final shrinkage, escrow-hold cascade |
| `routes/pledges.py` | 324 | pledges, designation lines, amend (OCC), remittance, write-off cascade |
| `routes/agencies.py` | 248 | agencies, reviews, certification fork, probation cascade, reinstatement reversal |
| `routes/cycles.py` | 241 | cycles, panel seats, award waterfall (OCC), impact-fund summary |
| `routes/requests.py` | 267 | request draft/submit, panel scores, finalize-review (trim), rescind |
| `routes/panelists.py` | 73 | panelist registry + reverse-FK reads |
| `routes/reports.py` | 256 | outcome reports, site visits, accept/revise/resubmit |
| `routes/clock.py` | 40 | `POST /_clock/set_current_utc` + delinquency re-derivation |

## Endpoint coverage
**55/55.** I extracted the PRD §4 endpoint table and diffed it against Flask's `url_map`: exact match, zero missing, zero extra (plus a non-API `GET /` readiness route). Storage is pure in-memory dicts — `grep` confirms no `sqlite`, no `open(`, no `/tmp`, no `seed`.

## Smoke test (port 53821, launched via `bash start.sh`, killed by PID)
Four scripted walks, all green:
- Happy path end-to-end: employer→coordinator→campaign→agency→review→certify→pledge→confirm→remit→cycle→seats→request→submit→3 scores→finalize→award→outcome report→site visit→complete→accept→clock move. Award came out `base 44130.00 / offset 0.00 / supplement 2647.80 / total 46777.80`, due date `awarded_at + 180`.
- PRD §3.8 worked example reproduced exactly: `175960.00 / 61586.00 / 3431.22 / 117805.22`.
- Negative paths: `ERR_ROLE_NOT_PERMITTED` 403, `ERR_UNAUTHENTICATED` 401 (unknown role, and missing `X-User-ID` for an entity-backed role), `ERR_STALE_VERSION` 412 on both OCC endpoints, `ERR_DUPLICATE_REQUEST_FOR_CYCLE` 409, `limit=0` → 400, pool conservation exact before/after rescind.
- All three cascades: escrow-hold (campaign `ESCROW_HOLD` → employer `SUSPENDED`/`ESCROW_HOLD_SHRINKAGE` → coordinator `INACTIVE` with its own version bump), write-off, and probation (certified 68.00 → `PROBATION`, `probation_count` 1, request `SUSPENDED_REVIEW` with `status_before_suspension`, cycle `RESTRICTED` at ratio 1.0) plus the reinstatement reversal (request restored, cycle `RESTRICTED → OPEN`).
- 5-score trim: 2 rows flipped `eligible=false`, composite = mean of the middle three, `eligible_score_count` stays at the pre-trim pool size (5).

## PRD adjudications
- **PRD beats scaffold on `resubmit`**: PRD §3.9 clears only `site_visit_findings` and deliberately keeps `site_visit_panelist_id` and the window; the scaffold's side-effect list wrongly clears all four. Implemented the PRD version.
- **Site-visit gate order**: the ladder is ascending (23, 28, 29, 34) but PRD §3.9 explicitly enumerates "First … Second … Third … Fourth" as segregation → seat → window sanity → spacing, corroborated by the scaffold preconditions. Implemented the prose order.
- **Site-visit completion ownership**: gate 6 precedes gate 21 in the ladder, but `site_visit_panelist_id` is null on an unscheduled report, so ownership is only evaluated when that field is non-null; otherwise the request falls through to `ERR_REPORT_INVALID_STATE`.
- **`version` semantics**: one increment per entity per request (a `flask.g` touch-set collapses repeated re-derivations of the same row), justified by PRD §2.4's "confirming a pledge re-derives four campaign totals yet the campaign is one mutation". Clock moves only bump agencies whose delinquency flag actually flipped.
- **Uniqueness without a dedicated code** → `ERR_INVALID_REQUEST` 400 at gate 3 (coordinator/panelist email, agency EIN, cycle year, review `(agency_id, fiscal_year)`); `donor_reference` uses gate 33 and duplicate panel seats use `ERR_DUPLICATE_PANEL_SCORE` per the scaffold.
- **Undeclared cycle freeze sources**: already `FROZEN` → `ERR_CYCLE_FROZEN`; from `DRAFT` → `ERR_CYCLE_NOT_OPEN` (documented in code).
- **Membership fork from `PROBATION`**: score >= 70 → `GOOD_STANDING` (the scaffold lacks the arrow, PRD §3.6 states it); probation band re-increments `probation_count` and re-runs links 3+4.
- Money/number fields reject JSON strings, per PRD §2.5 "monetary amounts are decimal numbers" and gate 3's declared-type rule.
- `remitted_on` is validated but not stored (Pledge has no such field); `expenditure_variance_pct` is 0.00 when `total_award` is null or zero.

## Step 5: Generate Unit Tests — 2026-09-03T22:35:00.000Z

Test generation is complete. Both output directories are at the task root; `workspace/implementation/` was never read or written.

## Output

`test_helpers/` (Stage 1, 1911 lines)
`types.py` 414 · `factories.py` 401 · `fixtures.py` 333 · `api_client.py` 324 · `assertions.py` 144 · `api_errors.py` 131 · `test_users.py` 69 · `constants.py` 67 · `__init__.py` 28

`test_suite/` (Stage 2, 7560 lines, **111 tests**)
| file | lines | tests |
|---|---|---|
| conftest.py | 45 | — |
| test_01_pledge_designation_fee_arithmetic.py | 426 | 6 |
| test_02_pledge_collection_and_write_off.py | 280 | 5 |
| test_03_campaign_lifecycle_and_shrinkage.py | 393 | 8 |
| test_04_agency_standing_and_probation_cascade.py | 248 | 5 |
| test_05_panel_review_scoring_thresholds.py | 220 | 4 |
| test_06_award_waterfall_and_tiers.py | 467 | 9 |
| test_07_award_gating_and_pool_conservation.py | 498 | 9 |
| test_08_outcome_reporting_and_site_visits.py | 568 | 9 |
| test_09_validation_precedence_conflicts.py | 374 | 8 |
| test_10_entity_shape_and_defaults.py | 623 | 11 |
| test_11_lifecycle_transition_guards.py | 599 | 8 |
| test_12_derived_calculation_results.py | 418 | 5 |
| test_13_request_validation_rules.py | 347 | 5 |
| test_14_endpoint_contracts_and_error_reachability.py | 1167 | 11 |
| test_15_role_separation_and_concurrency.py | 887 | 8 |

## Design-index coverage

67 live instances (22 `excluded_because:` stubs never translated). **66 translated, 1 skipped, 0 dangling tags, 0 tags on stubs.** Queue A: all 18 difficulty instances, each with 2–5 tests. Queue B: 48 of 49 live corner instances, 1 test each — entities 11, state_machines 8, calculations 5, validations 5, endpoints 4, errors 7, rbac 4, complexity_layers 3, consistency_model 1.

**Skipped (gap left as a gap, no placeholder/xfail):** `Corner/state_machines/allocation_cycle_initial_posture_is_draft_with_zero_available_pool` — the instance asserts a new cycle's `available_undesignated_pool == 0.00`, but PRD §3.7 says it "is created in `DRAFT` posture with `available_undesignated_pool` equal to `opening_undesignated_pool`". The PRD does not derive the asserted outcome, so the instance fails condition 2 of the filter.

## Adjudications where the PRD overrode the design yaml (instance still translated)

- `optimistic_concurrency_..._allocation_cycle_version_on_award`: the yaml's literal `v_open == 2` / `v_final == 3` ignores that request submission re-derives cycle counters and is therefore a cycle mutation under §2.4. The test asserts the relational facts instead (draft-era version refused 412 → freshly read version awards 34556.00 → replay refused 412; version strictly advances) plus the exact money (`base_award` 32600.00, supplement 1956.00, available 165444.00).
- Two corner instances assert `recorded_pledge_count == 1` on a still-`DRAFT` pledge; PRD §3.1 counts only `CONFIRMED`/`AMENDED`/`LOCKED`, so the tests assert 0 while `DRAFT` and 1 immediately after confirmation.

## Verification performed

- Every file written in chunked `cat >>` appends; each verified with `ast.parse` and `wc -l`.
- `python3 -m pyflakes` clean across all 25 files (only conftest's deliberate `noqa: F401` side-effect import).
- Citation pass: 163 `PRD <section>: "…"` quotes, all matched **verbatim** against PRD.md **and** confirmed to lie inside the section they are labelled with; every test has exactly one `Design:` line and it is the last line of the docstring.
- Scaffold-citation pass: zero occurrences of "scaffold" or any `§` token anywhere in the generated code (two `§`-bearing PRD quotes in test_15 were swapped for equivalent §-free sentences).
- `pytest --collect-only`: **111 tests collected**, no import errors. `__pycache__`/`.pytest_cache` removed.

Orchestrator hygiene check: `test_helpers/` (9 .py) and `test_suite/` (16 .py) both confirmed at the task root; no copies inside `workspace/`.

## Step 7: Test & Fix Loop — 2026-09-03

3 iterations, each an 8-round parallel `per-test-server` sweep (111 tests/round).

| iter | per-round result | union failures |
|---|---|---|
| 1 | 10 passed / 101 failed | 101 (deterministic across all 8 rounds) |
| 2 | 108 passed / 3 failed | 3 (deterministic) |
| 3 | **111 passed / 0 failed** | 0 |

No flakiness observed: every round of every iteration produced an identical
pass/fail set, so no timing-sensitive defect was in play.

### Iteration 1 → 2: `test_helpers/factories.py` sent money as JSON strings

All 101 failures were one test-helper bug. Every payload builder emitted its
decimal fields as quoted strings (`"1000.00"`, `"0.7800"`), but PRD 2.5 declares
"All monetary amounts are decimal numbers carried to exactly 2 decimal places",
and PRD 2.10 gate 3 rejects a value not "matching its declared type" with
`ERR_INVALID_REQUEST` (400). The PRD-faithful implementation correctly refused
them, so the failures surfaced as setup errors (`Field 'program_expense_ratio'
must be a number.` × 53, `loss_reserve_amount` × 31, `opening_undesignated_pool`
× 9, `gross_amount` × 1) plus 7 tests whose expected `error_id` was masked by the
400. Fix: added `factories.as_number()` and applied it to every money / ratio /
numeric-measure parameter (`loss_reserve_amount`, `designated_amount`,
`gross_amount`, `amount`, the three self-reported and three audited review
figures, `opening_undesignated_pool`, `max_award_per_agency`,
`requested_amount`, `funds_expended`, `outcome_metric_value`). It converts a
readable decimal literal to a JSON number and passes a non-numeric value through
untouched, so the declared-type probes in test_10 still send their bad values
verbatim. The three raw pledge probe dicts in test_10 were switched to numeric
literals for the same reason.

### Iteration 2 → 3: fresh amendment lines and `collected_designated_amount`

The 3 remaining failures all asserted that a designation line *freshly created by
an amendment* already carries `collected_designated_amount` rescaled by the
pledge's collection ratio (69.56 / 34.78 / 92.75 / 111.30), plus the
`designated_passthrough_ytd` figures derived from them.

PRD does not uniquely determine this. PRD 3.4 says "A successful amendment does
five things and then advances the state" and enumerates them — supersede the old
lines, create one fresh `ACTIVE` line per element, re-run the fee allocation over
"`designated_amount_total`, `undesignated_amount`, `designation_fee_total` and
`net_designated_total`", re-derive the passthrough, increment `amend_count` —
never mentioning `collected_designated_amount` on the new lines. The rescaling
rule lives in PRD 3.5 and is explicitly event-scoped: "Each remittance also flows
down to the designation lines … each line's `collected_designated_amount` becomes
its `net_designated_amount` multiplied by the pledge's collection ratio". Two
faithful readings therefore exist: a fresh line starts at 0.00 and is rescaled by
the *next* remittance, or the amendment re-derives it immediately. Per STEP 1c
the tests were split rather than deleted — the covered assertions (fee re-run,
gross decomposition, `amend_count`, `version`, both axis statuses, per-line
`processing_fee` / `net_designated_amount`, the superseded line frozen at 0.00,
the superseded/all-lines counts, campaign aggregates, and agency B's 0.00
passthrough, which both readings agree on) all stay; only the non-derivable
`collected_designated_amount` values and the two passthrough figures computed
from them were removed. No implementation change was required, and the
`test_final_remittance_...` test still pins the PRD 3.5 rescaling on the
remittance path.

**Fixes to `implementation/`: none.** No endpoint, field, side effect or check was
added, removed or weakened in `workspace/implementation/` during Step 7.

### Step 7 — orchestrator record (subagent's returned summary, verbatim)

Clean 8-round sweep achieved: **111/111 passing in all 8 parallel rounds.**

**Iterations run:** 3 (each an 8-round concurrent `per-test-server` sweep, 111 tests/round)

| iter | per-round | union failures |
|---|---|---|
| 1 | 10 passed / 101 failed | 101 |
| 2 | 108 passed / 3 failed | 3 |
| 3 | **111 / 0** | 0 |

No flakiness anywhere — every round of every iteration produced an identical pass/fail set, so no timing-sensitive defect was in play.

**Tests deleted:** none. Two assertions groups were *split* per STEP 1c (partial coverage), not deleted.

**Fixes applied to `test_helpers/`:**
- `test_helpers/factories.py` — added `as_number()` and applied it to every money/ratio/numeric-measure parameter (`loss_reserve_amount`, `designated_amount`, `gross_amount`, `amount`, the three self-reported + three audited review figures, `opening_undesignated_pool`, `max_award_per_agency`, `requested_amount`, `funds_expended`, `outcome_metric_value`). All 101 iteration-1 failures were this one bug: the builders emitted decimals as JSON *strings*, but PRD 2.5 declares "All monetary amounts are decimal numbers…" and PRD 2.10 gate 3 rejects a value not "matching its declared type" with `ERR_INVALID_REQUEST` — so the PRD-faithful implementation correctly refused them. `as_number` passes non-numeric values through untouched so the declared-type probes still send their bad values verbatim.

**Fixes applied to `test_suite/`:**
- `test_10_entity_shape_and_defaults.py` — the three raw pledge probe dicts now use numeric literals, so each probe exercises its intended rule (bad enum / 3 decimals / zero amount) rather than tripping on type.
- `test_01_pledge_designation_fee_arithmetic.py`, `test_02_pledge_collection_and_write_off.py` — removed the assertions that a designation line *freshly created by an amendment* already carries `collected_designated_amount` rescaled by the collection ratio (69.56/34.78/92.75/111.30), plus the two passthrough figures derived from them. PRD 3.4's "A successful amendment does five things" enumeration never mentions that field, and the rescaling rule in PRD 3.5 is explicitly event-scoped to "Each remittance also flows down to the designation lines" — so two faithful readings exist (fresh line starts at 0.00 and is rescaled by the next remittance, vs. rescaled immediately). Unique derivability fails. Everything covered stayed: fee re-run, gross decomposition, `amend_count`, `version`, both axis statuses, per-line `processing_fee`/`net_designated_amount`, the superseded line frozen at 0.00, line counts, campaign aggregates, and agency B's 0.00 passthrough (both readings agree). PRD 3.5's rescaling is still pinned by `test_final_remittance_closes_the_collection_axis_and_leaves_the_pledge_amended`.

**Fixes applied to `implementation/`:** none. No endpoint, field, side effect or check was added, removed or weakened in `workspace/implementation/`.

**Orchestrator independent verification** (per pipeline guidance that a Step 7 subagent can claim a clean sweep without leaving artifacts): I re-read all 8 `workspace/implementation/results.*.json` myself. All 8 files exist and each reports `passed=111, failed=0, total=111`. Claim confirmed against artifacts, not taken on trust.

**Step 8 gating decision:** NOT skipped. The skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes on the first sweep. Step 7 ran 3 iterations with fixes in both `test_helpers/` and `test_suite/`, so PRD-silence sites exist (notably the amendment-vs-`collected_designated_amount` ambiguity and the money-type declaration) and Step 8 must run.

## Step 8: Finalize PRD — 2026-09-04T00:20:00.000Z

Done. One edit was warranted; the rest of the Step 7 diff was fixture-only.

## PRD.md vs PRD_FINALIZED.md
- Lines: 455 → 455 (0.00% delta); bytes 95,134 → 95,559 (+0.45%). One line rewritten in place (line 233).

## Change list
- **§3.4 (amending a designation line set)** — *insert* — pins that each fresh `ACTIVE` line created by an amendment is born with `collected_designated_amount` at 0.00, that the amendment never rescales the new lines by the pledge's collection ratio even on an already partly-collected pledge, and that consequently a fresh line contributes 0.00 to the gaining agency's re-derived `designated_passthrough_ytd` until a later remittance rescales it — `implementation/routes/pledges.py:47-63` (`_create_lines`, `collected_designated_amount: ZERO`), `implementation/routes/pledges.py:238-247` (amend creates fresh lines, calls only `calc.allocate_designation_fees`, then re-derives passthrough), `implementation/services/calc.py:63-95`.

## Per-edit pre-edit search log
**Edit 1 — §3.4 fresh-line collected share**
- (a) Subject: the `collected_designated_amount` field of a designation line — every site that writes it, every site that reads it, and every operation that creates lines.
- (b) Paths enumerated (grepped `collected_designated_amount` and `scale_collected_designated` across all of `implementation/`, 5 write sites + 1 read site, all read):
  - `routes/pledges.py:58` `_create_lines` — initializes to 0.00; shared by **both** `record_pledge` (§3.3) and `amend_designations` (§3.4).
  - `routes/pledges.py:159-179` `record_pledge` — line creation at recording (pledge `PENDING`, `collected_amount` 0.00, so 0.00 under either reading).
  - `routes/pledges.py:231-247` `amend_designations` — supersedes old lines to 0.00, creates fresh lines, runs `allocate_designation_fees` only; no rescale call.
  - `routes/pledges.py:283-287` `record_collection` → `services/calc.py:86-95` `scale_collected_designated` — the sole rescaling path, `ACTIVE` lines only, ratio `collected/gross`, `q2`.
  - `routes/pledges.py:316-320` write-off — `ACTIVE` lines → `UNCOLLECTED` with 0.00.
  - `services/aggregates.py:146-153` `recompute_agency_passthrough` — sums `collected_designated_amount` over **all** `ACTIVE` lines pointing at the agency, across every campaign.
- (c) Wording adjustments made: (1) said "contributes 0.00 to the receiving agency's re-derived `designated_passthrough_ytd`" rather than "the agency's passthrough is 0.00", because the passthrough sums that agency's `ACTIVE` lines across all pledges/campaigns and other lines may carry value; (2) said "only a later remittance … lifts a fresh line's collected share above zero" rather than "the next remittance rescales it", so the sentence stays true where no further remittance is possible (a `COLLECTED` or `WRITTEN_OFF` pledge that is amended keeps the fresh line at 0.00) and does not conflict with the write-off cascade zeroing the same field; (3) scoped the claim to lines created *by an amendment* while leaving §3.3's recording path undisturbed (identical impl behavior, but no new universal claim about line creation was introduced).

**Items deliberately not patched**
- `test_helpers/factories.py` `as_number()` and the three `test_10` raw pledge probes: pure fixture bugs. `implementation/validators.py:80-137` rejects JSON strings for money/ratio/numeric fields with `ERR_INVALID_REQUEST`, which PRD 2.5 ("All monetary amounts are decimal numbers…") plus PRD 2.10 gate 3 ("every value matching its declared type… money fields carrying at most 2 decimals and ratio fields at most 4") already determine uniquely; integers are accepted for money, consistent with gate 3's "at most 2 decimals". No PRD silence, so no edit. (I also checked `get_number` for `outcome_metric_value` at `routes/reports.py:72,234` — no decimal-place cap; PRD is silent and declares it neither money nor ratio, so the existing under-determined wording already matches the impl and narrowing it would create a new mismatch.)
- No implementation fixes were made in Step 7, so nothing else in the diff traces to a PRD/impl divergence.

Orchestrator verification: `PRD_FINALIZED.md` exists, is 455 lines, and differs from `PRD.md` at exactly one line (line 233) — confirmed by `diff`. It is not a byte-identical copy, so the finalizer did real work.

## Step 9: Complete PRD — 2026-09-04T01:10:00.000Z

Orchestrator decision (recorded per the autonomy instruction): Step 9 was run as **three sequential file-partitioned passes** over `implementation/` rather than one single-shot subagent. Rationale: a single Step 9 agent facing a 19-module / 3131-line implementation and a 455-line PRD reliably under-scans and can exit leaving `PRD_COMPLETED.md` byte-identical to its source, which is indistinguishable from "nothing to fix" but is actually a silent no-op. Partitioning forces exhaustive coverage of every module. Passes were run strictly sequentially (never concurrently) because all three edit the same file; pass 1 owned the `cp` from `PRD_FINALIZED.md`, passes 2 and 3 were explicitly forbidden to `cp` and told what the earlier passes had already pinned.

Partition:
- Pass 1 — cross-cutting/global: `app.py`, `errors.py`, `store.py`, `envelope.py`, `validators.py`, `auth.py`
- Pass 2 — calculations, aggregates/cascades, employers, campaigns, pledges: `services/calc.py`, `services/aggregates.py`, `routes/employers.py`, `routes/campaigns.py`, `routes/pledges.py`
- Pass 3 — remaining routes: `routes/agencies.py`, `routes/cycles.py`, `routes/requests.py`, `routes/panelists.py`, `routes/reports.py`, `routes/clock.py`, plus two carry-over items pass 2 flagged and deferred

### Pass 1 (global layers) — 12 ambiguity-pins, 1 mismatch-revision

`workspace/PRD_COMPLETED.md` created as a byte copy of `PRD_FINALIZED.md`, then edited surgically (13 Edit calls, no whole-file writes). Exit: 456 lines / 99,599 bytes (from 455 / 95,559).

- §2.1 ¶1 — revise — mismatch — "every request must carry two headers" softened: header values are exact strings, an empty value counts as absent, and `X-User-ID` is mandatory only for the three entity-backed roles — `auth.py:26-34`
- §2.1 last ¶ — insert — ambiguity — an `X-User-ID` naming no persisted coordinator/agency fails the ownership comparison with `ERR_OWNERSHIP_VIOLATION` rather than yielding a 404, because the header is compared, never resolved — `auth.py:100-110`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` plus exactly 20 chars from A–Z/0–9 — `envelope.py:12,21`
- §2.2 — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall time — `envelope.py:25`, `store.py:91`
- §2.2 — insert — ambiguity — pagination `meta` fields are absent from single-object responses — `envelope.py:46,54-59`
- §2.2 — insert — ambiguity — error `message` wording is not contractual; only `error_id` and status are — `errors.py:76-78`
- §2.2 — insert — ambiguity — unrouted paths / undeclared methods / unexpected failures ride the same envelope as `ERR_INVALID_REQUEST` with the framework's status (404, 405, 500), so `ERR_INVALID_REQUEST` is not always HTTP 400 — `app.py:62-73`
- §2.3 ¶1 — insert — ambiguity — non-integer or out-of-bound `limit`/`offset` → `ERR_INVALID_REQUEST` 400, never clamped; empty value = omitted; offset past the end returns empty `data` with unpaginated `total_count` — `envelope.py:78-105`
- §2.3 ¶2 — insert — ambiguity — ties on any stated sort key break by creation order — `store.py:150-155`
- §2.3 ¶3 — insert — ambiguity — filters match exactly, empty = omitted, year filters must parse as integers, boolean filters accept true/false, 1/0, yes/no in any case — `envelope.py:108-134`
- §2.4 ¶2 — insert — ambiguity — a row re-derived several times while serving one request increments `version` once — `store.py:127-147`
- §2.5 ¶1 — insert — ambiguity — decimal fields serialize as JSON numbers, so trailing zeros are lost on the wire — `envelope.py:28-42`
- §2.10 gate 3 — insert — ambiguity — absent/empty body = `{}`; non-JSON or non-object body → 400; explicit `null` = absent; numeric strings and booleans rejected for numeric fields; strings must be non-blank after trimming yet stored untrimmed; undeclared fields ignored — `validators.py:23-77`
- §4 intro — insert — ambiguity — trailing slash is insignificant in path matching — `app.py:25`

### Pass 2 (calc/aggregates/employers/campaigns/pledges) — 13 ambiguity-pins, 4 mismatch-revisions

Entry 456 lines / 99,599 bytes → exit 456 lines / 104,813 bytes. Pass 1's 12 edited lines verified byte-identical at exit.

- §2.8 — revise — mismatch — escrow fan-out flips "each one that is still `ACTIVE`", not every coordinator row — `routes/campaigns.py:173-176`
- §3.1 — revise — mismatch — `active_campaign_count` is re-derived at exactly three moments (campaign create, open, reconcile), not on close-solicitation; unconditional, so the employer row mutates even when the count is unchanged — `routes/campaigns.py:79,96,177`; `services/aggregates.py:81-88`
- §3.1 — revise — mismatch — `coordinator_role` grants no capability difference, and a coordinator's own `status` gates nothing — `auth.py:100-105`; `routes/pledges.py:66-72`
- §3.1 — insert — ambiguity — duplicate coordinator `email` is a gate-3 `ERR_INVALID_REQUEST` (400), refused before the path `employer_id` is resolved — `routes/employers.py:105-108`
- §3.1 — insert — ambiguity — `recorded_pledge_count` re-derived at exactly two moments (record by a coordinator, confirm), unconditionally — `routes/pledges.py:181,200`
- §3.2 — insert — ambiguity — non-strictly-later `solicitation_end_date` is a gate-3 400 ahead of FK resolution; `campaign_year` carries no uniqueness constraint; all five money aggregates created at 0.00 rather than null — `routes/campaigns.py:37-38,56-77`
- §3.2 — insert — ambiguity — the four confirmed-gross totals are re-derived only on confirm/amend, and `projected_payroll_pledge_total` exactly once, at close-solicitation — `routes/campaigns.py:111`; `routes/pledges.py:199,244`
- §3.3 — insert — ambiguity — `recorded_by_coordinator_id` is null when a `UnitedFundAdmin` records — `routes/pledges.py:162,180-181`
- §3.3 — insert — ambiguity — fee allocation runs at record time while still `DRAFT`; a pledge with no `designations` lands with totals 0.00 and `undesignated_amount` = full gross — `routes/pledges.py:179`; `services/calc.py:74-83`
- §3.3 — insert — ambiguity — confirmation's passthrough re-derivation is unconditional — `routes/pledges.py:203-205`; `services/aggregates.py:146-153`
- §3.4 — insert — ambiguity — `expected_pledge_version` must be a non-negative integer (otherwise 400, not 412); the mandatory `designations` array may be empty — `routes/pledges.py:213`; `validators.py:170-186`
- §3.4 — insert — ambiguity — a superseded line keeps its `designated_amount`, `designation_sequence`, `processing_fee` and `net_designated_amount`; only `collected_designated_amount` is zeroed — `routes/pledges.py:231-236`
- §3.5 — insert — ambiguity — `remitted_on` is validated but never persisted; a remittance creates no record of its own — `routes/pledges.py:256`
- §3.5 — insert — ambiguity — every `ACTIVE` line and holding agency is mutated by the rescaling regardless of whether the value moved; campaign totals untouched by a remittance — `routes/pledges.py:283-287`; `services/aggregates.py:148-151`
- §3.5 — revise — mismatch — the `RECONCILED` fork does not leave "nothing further" (both forks re-derive the employer's `active_campaign_count`); an already-`SUSPENDED` employer is re-stamped rather than refused; only still-`ACTIVE` coordinators flip — `routes/campaigns.py:163-177`
- §3.7 — insert — ambiguity — the two trimmed rows are always distinct (high first, low from the remainder), so an all-identical pool drops its two earliest — `services/calc.py:215-241`
- §3.7 — insert — ambiguity — eligible-pool membership turns on the conflict-free seat alone, never on the score's own `eligible` flag — `services/aggregates.py:293-301`

### Pass 3 (remaining routes + carry-overs) — 14 ambiguity-pins, 8 mismatch-revisions

Entry 456 lines / 104,813 bytes → exit 456 lines / 110,382 bytes. All 28 headings intact; pass 1/2 markers all still present.

- §2.3 — insert — ambiguity — on a list nested under a path resource the parent is resolved before `limit`/`offset`/filter parsing, so an unknown parent + malformed page param answers the 404; gate 3-before-gate 4 governs write bodies only — `routes/agencies.py:33,44`, `routes/cycles.py:38`, `routes/panelists.py:32,43`, `envelope.py:203-215`
- §2.7 — revise — mismatch — clock move re-derives delinquency for every agency and in both directions (raises and clears), mutating only rows whose flag actually flipped; plus accepted `to_iso8601` forms and `current_utc` rendered with three fractional digits — `routes/clock.py:90-113`, `services/aggregates.py:213-226`
- §3.9 — insert — ambiguity — report-filing / acceptance / award triggers mutate the agency row unconditionally; the clock sweep only on actual flip — `routes/cycles.py:240`, `routes/reports.py:104,207`
- §2.4 — insert — ambiguity — flags the clock sweep as the one re-derivation that is not unconditionally a mutation — `services/aggregates.py:222-226`
- §2.6 — insert — ambiguity — both `expected_*_version` fields are gate-3 integers >= 0; non-integer/negative → 400, not 412 — `routes/cycles.py:199`, `routes/pledges.py:213`
- §2.10 item 17 — revise — mismatch — freezing itself is an `ERR_CYCLE_FROZEN` site (re-freeze) — `routes/cycles.py:179`
- §2.10 item 18 — revise — mismatch — freezing requires `OPEN`/`RESTRICTED`, so freezing a `DRAFT` cycle → `ERR_CYCLE_NOT_OPEN` — `routes/cycles.py:181`
- §2.10 items 28/29/34 — revise x3 — mismatch — pinned the real site-visit order: report status → segregation → seat → window sanity → spacing — `routes/reports.py:127-156`
- §3.6 — revise — mismatch — review filing has no ownership check: any `AgencyRepresentative` may file against any agency — `routes/agencies.py:93-95`
- §3.6 — insert — ambiguity — idempotent `UNDER_FINANCIAL_REVIEW → UNDER_FINANCIAL_REVIEW` on a second pending packet, and `open_review_count` is re-derived as the count of `PENDING` reviews — `routes/agencies.py:138-139`, `services/aggregates.py:167-173`
- §3.6 — insert x2 — ambiguity — `ein` and per-agency `fiscal_year` collisions → `ERR_INVALID_REQUEST` (400) at gate 3 — `routes/agencies.py:70-75,107-109`
- §3.6 — insert — ambiguity — audited figures carry the same ranges/decimal limits as their self-reported counterparts — `routes/agencies.py:166-172`
- §3.7 — revise — mismatch — every filed score (not just the first) re-derives `eligible_score_count` and bumps the request's `version` — `routes/requests.py:203-206`
- §3.7 — insert — ambiguity — freeze from `FROZEN` → `ERR_CYCLE_FROZEN`; from `DRAFT` → `ERR_CYCLE_NOT_OPEN` — `routes/cycles.py:179-182`
- §3.7 — insert x2 — ambiguity — `cycle_year` and panelist `email` collisions → 400 at gate 3 — `routes/cycles.py:100-102`, `routes/panelists.py:57-62`
- §3.8 — insert — ambiguity — the body `request_id` is not cross-checked against the path cycle; the waterfall reads the path cycle's ceiling/pool and only the path cycle's totals are re-derived — `routes/cycles.py:201-239`
- §3.8 — insert — ambiguity — the summary's three component totals and `awarded_request_count` cover `AWARDED`/`REPORTING`/`CLOSED_SATISFIED` — `routes/cycles.py:57-58`, `services/aggregates.py:25`
- §3.9 — revise — mismatch — the site-visit-completion ownership comparison applies only once a visit is scheduled; a null `site_visit_panelist_id` falls through to `ERR_REPORT_INVALID_STATE` — `routes/reports.py:176-180`
- §3.9 — insert — ambiguity — `outcome_metric_value` has no decimal-place limit, stored as supplied — `routes/reports.py:72`, `validators.py:128-137`

Carry-over resolution: (1) the 404-before-400 ordering on nested list reads was pinned in §2.3 rather than §2.10, because gate 3 is explicitly scoped to write bodies and editing the gate there would have introduced a contradiction; verified live (`GET /agencies/nope/reviews?limit=999` → `ERR_AGENCY_NOT_FOUND`, same call with a real parent → `ERR_INVALID_REQUEST`). (2) the conditional clock sweep was pinned in §2.7 (primary), §3.9 (contrast with the unconditional triggers) and §2.4 (hedge); the pass also caught that the old prose implied the sweep only raises the delinquency flag when it in fact clears it too.

### Step 9 totals and orchestrator verification

39 ambiguity-pins + 13 mismatch-revisions across the three passes (52 edits total).

- `PRD.md` 455 lines / 95,134 bytes → `PRD_FINALIZED.md` 455 lines / 95,559 bytes → `PRD_COMPLETED.md` **456 lines / 110,382 bytes** (+15.5% over PRD.md).
- `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md`; `diff` shows 97 changed lines (48 revised + 1 added). The scan demonstrably ran — this was the specific failure mode the three-pass split was chosen to prevent.
- `tail` confirms the file ends on the complete final row of the §5 error catalogue (`| ERR_POOL_INSUFFICIENT | 422 |`) — a real section boundary, not truncated.
- Step 9 touched documentation only. `implementation/` was not modified, and all 8 `results.*.json` from the Step 7 final sweep still read 111/111. No SQLite/JSON persistence files exist in `implementation/`.

## Pipeline complete

All nine steps finished. Final state: 111 tests, 8/8 clean parallel rounds, `workspace/PRD_COMPLETED.md` written.
