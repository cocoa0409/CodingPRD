# Worklog — task_2491_product_sampling_seeding_campaign

## Step 1: Create task directory — 2026-09-03T00:59:31.276Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2491_product_sampling_seeding_campaign` and `.../workspace`. Index pre-assigned by the invoking pipeline (2491); no scan of ./tasks/ performed, per orchestration instructions (32 concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-03T03:17:40.940Z

All three scaffold artifacts are complete and the lint is clean.

## Verdict block (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2491_product_sampling_seeding_campaign/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2491_product_sampling_seeding_campaign/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2491_product_sampling_seeding_campaign/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    65
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     90
  Calls scanned (§1.8+§1.9):  1260

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Artifacts

- `SCAFFOLD.yaml` — 13 entities, 9 state machines, 2 concurrency rules, 14 calculations, 33 validations, 65 endpoints, 51 errors, 6 roles; top-level keys contain no `*_design` key.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`, 9 rule_ids × 2 = 18 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`, 110 instances (90 recipes + 20 `excluded_because` stubs) across all nine guide sections: entities 13, state_machines 17, calculations 14, validations 21, endpoints 7, errors 22, rbac 8, cross_cutting_complexity_layers 6, consistency_model 2.

## Defects found and fixed in this pass

1. **FK_REVERSE_UNREACHABLE (the only lint violation).** `PurchaseMatch.enrollment_id` was only reachable via `GET /enrollments/{enrollment_id}/purchase-matches`; the lint's sub-resource form requires the literal placeholder `{id}`, so it did not count. Fixed by adding the filtered-list channel: `GET /purchase-matches/{purchase_match_id}` (needed to derive the collection segment) and `GET /purchase-matches` with `enrollment_id?`/`qualified?` filters. That introduced `ERR_PURCHASE_MATCH_NOT_FOUND`, which was added to §1.6, to validation 7's 404 union, and covered by a new §1.9 instance `errors/get_unknown_purchase_match_not_found`.
2. **`rbac/fulfillment_ops_cannot_open_campaign_screening` had three wrong asserts.** It asserted `version == ${camp_v}` captured before a `POST /kit-lines` that increments `Campaign.version`, plus `kit_assembly_unit_cost_cents == 0` (the create recomputes it to 283) and `budget_available_cents == 0`. Now captures the version via a `GET /campaigns/{id}` after setup and asserts 283 / committed 0 / available 1000000.
3. **Two asserts contradicted `POST /campaigns` side effect "sets budget_available_cents = budget_total_cents".** `entities/campaign_creation_returns_the_full_declared_field_set` and `state_machines/open_screening_without_an_active_kit_line_is_rejected` claimed `budget_available_cents == 0`, inventing a "seeded only at open-screening" rule; both now assert 1000000 (and the latter's `distinguishing_aspect` no longer says "no budget is seeded").
4. Cosmetic: the 51-row error-coverage map in the corner-design header is re-padded to a uniform dot column, and `ERR_PANELIST_NOT_FOUND` / `ERR_CAMPAIGN_NOT_ACCEPTING_ENROLLMENTS` now point at the instances that actually trigger them.

## Verification performed beyond the lint

Scripted replays over all 108 recipes: name uniqueness across both files (0 dups), stub well-formedness (20 stubs, all `difficulty_instance` citations resolve, none carries `test_recipe`), placeholder closure in calls *and* asserts (0 unresolved), clock pinned as the first setup call everywhere, asserted HTTP status vs §1.5 `code`/§1.6 `http_status` (0 mismatches), error-code spelling and full catalogue coverage (all 51 codes triggered, 0 unknown codes), budget conservation `committed + available == total` (11 pairs), Campaign counter replay (enrollment/allocated/delivered/approved/disclosure-rejected/syndicated), KitLine four-bucket unit replay (23 recipes), and a §1.2 transition replay of every successful call (campaign lifecycle, kit-line retire, wave lock/release, screening, shipment, review, syndication, diversion). All residual flags were traced to simulator simplifications or deliberately scoped mid-recipe asserts, not to the artifacts.

## Step 3: Copy shared files — 2026-09-03T03:17:59.446Z

Copied `./INSTRUCTION.md` → `tasks/task_2491_product_sampling_seeding_campaign/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T03:35:11.614Z

Orchestrator truncation check (per invocation instructions): PASS. `PRD.md` is 505 lines; `grep -n '^#'` shows all five top-level sections (§1 Introduction, §2 Global Specifications, §3 Business Logic & Workflows, §4 Endpoint Definitions, §5 Error Code Catalogue) with §3 carrying all nine subsections; the tail ends on a complete final table row (`| ERR_CAMPAIGN_BUDGET_EXHAUSTED | 422 Unprocessable Entity |`) at a real section boundary, not a mid-sentence cut. No regeneration needed.

Subagent summary (verbatim):

PRD generation complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2491_product_sampling_seeding_campaign/workspace/PRD.md` — **505 lines**, ~13,900 words. Tail verified: the file ends with the final row of the §5 error table (`ERR_CAMPAIGN_BUDGET_EXHAUSTED | 422 Unprocessable Entity`), a real section boundary with no mid-sentence cut and no audit footer.

**Structure:** §1 Introduction; §2 Global Specifications (2.1 RBAC → 2.11 Derived Counters and Cascading Consistency, 11 domain-derived subsections); §3 Business Logic & Workflows in 9 freely-grouped subsections (campaign + kit composition, campaign lifecycle, panel recruitment + fraud scoring, enrollment/screening/holdout, inventory + wave capacity, allocation through delivery + per-sample cost, review collection + moderation, retailer syndication + takedown, diversion + conversion matching + lift); §4 Endpoint Definitions; §5 Error Code Catalogue.

**Hard Contract PASS reports**

Contract 1 — Field-Name Coverage: **PASS**. 145 required identifiers extracted mechanically from SCAFFOLD.yaml (all entity fields incl. per-entity common fields, all endpoint `input` names with `?` stripped, all path-template params, all computed-read output field names). Every one appears verbatim inside backticks in PRD.md. Missing: none.

Contract 2 — Rule Coverage: **PASS**. All six high-risk categories covered, plus the tail:
- Validation priority ordering: all 33 rungs enumerated in order in §2.5 with error ID, HTTP status and scope; additional pinned sub-orders written for screening's four checks (§3.4), allocation's rung-10 sub-order (§3.6), the four submission gates (§3.7), the retailer's three dispatch rules (§3.8) and the four-step diversion-penalty evaluation (§3.9).
- OCC / concurrency: §2.8 pins both tokens (`expected_campaign_version` → `ERR_STALE_CAMPAIGN_VERSION`, `expected_enrollment_version` → `ERR_STALE_ENROLLMENT_VERSION`) and states no other endpoint accepts one; restated where each is consumed.
- Cross-entity side effects: depth-3 shipment-cancellation chain and depth-4 diversion-substantiation chain written hop-by-hop in §2.11, §3.6 and §3.9, including the "cascade-only transitions cannot be requested directly" rule.
- `applies_to` scopes: every scoped error carries its operation list (unions taken where scaffold `validations` and `errors` disagreed — `ERR_PANELIST_BANNED` 8 ops, `ERR_CAMPAIGN_POSTURE_FROZEN` 5 ops, etc.).
- Field-level structured content: `screening_answers` (replace-wholesale object), `reserved_line_units` (kit-line→units mapping), `target_segment_codes`, `syndication_retailer_ids` (left-to-right FK validation), and the cost-summary read's 10-field shape.
- Sibling-branch symmetry: 3-way moderation branch, dispatch `SYNDICATED` vs `REJECTED` (disjoint counter effects), deliver vs report-lost, screening pass vs fail, `ITT` vs `PER_PROTOCOL`, provisional vs final cost variants.
- Tail: all 9 state machines' transitions present (every transition target string appears); all 14 calculations with their constants (mechanical check: no scaffold calculation constant absent); all 51 error IDs referenced in prose above §5, not just in the table.

Contract 3 — §3 Path Purity: **PASS**. 277 distinct backticked tokens in §3; zero start with `/`, zero are a bare HTTP method, zero combine method+path. Zero unbackticked raw paths in §3 either.

**Additional verifications:** §2.2 is byte-identical to `skills/prd-bench-doc-generator/section-2.2-response-structure.md`; §4 table has exactly 65 rows matching the scaffold's method+path set with no extras or omissions; §5 table has exactly 51 rows with zero HTTP-status mismatches against the scaffold; no fuzzy quantifiers ("approximately", "roughly", "conservatively") and no pseudocode operators (`==`, `>=`, `&&`, `->`) anywhere in the document.

The hard constraint was honoured: neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was read, grepped or referenced.

## Step 5: Generate unit tests — 2026-09-03T04:59:37.644Z

ORCHESTRATOR DEVIATION + MITIGATION (recorded per the autonomy directive — decided without escalation). The skill requires Steps 5 and 6 to be launched in a SINGLE assistant message so that the implementation generator starts before `test_suite/` exists and therefore cannot read it. The orchestrator launched Step 5 alone, so that physical isolation was lost. Rather than accept a weaker prompt-only prohibition, the orchestrator restored physical isolation by moving `test_suite/` and `test_helpers/` out of the repository entirely to `/tmp/prd_bench_2491_tests_hold/` before spawning Step 6, so the impl generator observes exactly the directory state it would have seen under concurrent launch (no test artifacts anywhere under `tasks/`). Both directories are moved back before Step 7 runs, and a file count is verified on restore. Step 5's own generation was unaffected — it ran before Step 6 existed and was explicitly forbidden from reading `workspace/implementation/`.

Subagent summary (verbatim):

Test generation is complete. Both remaining queue-B sections are translated and the whole suite passes the full audit.

## What was delivered

`/home/ubuntu/github/CodingPRD/tasks/task_2491_product_sampling_seeding_campaign/test_helpers/` — 8 modules (`types.py`, `constants.py`, `api_errors.py` with all 51 codes + the HTTP-status map registration, `test_users.py`, `api_client.py` = `SamplingApiClient` over all 65 endpoints, `factories.py`, `assertions.py`, `fixtures.py` with five tiers of world builders, `__init__.py` barrel).

`/home/ubuntu/github/CodingPRD/tasks/task_2491_product_sampling_seeding_campaign/test_suite/` — 18 files, **141 tests**, all collected cleanly (`pytest --collect-only` = 141):
- 54 tests for queue A (`test_01`–`test_09`), every one of the 27 difficulty instances covered by >=2 tests.
- 87 tests for queue B (`test_10`–`test_18`): entities 11, state_machines 14, calculations 7, validations 17, endpoints 7, errors 18, rbac 7, cross_cutting 4, consistency_model 2.

New this segment:
- `test_suite/test_17_cross_cutting.py` — the 4 live `cross_cutting_complexity_layers` instances: the full lift-analysis OCC cycle on the campaign parent (201 -> replayed 412 `ERR_STALE_CAMPAIGN_VERSION` -> refreshed retry 201 -> `superseded` flip, `total_count == 2`); the allocation OCC rejection on the pre-screen enrollment version, proving rung 12 fires ahead of capacity/stock/budget and leaves kit units, wave count and budget at zero; the positive reship half (`FORFEITED -> NONE`, `supersedes_shipment_id`, LOST stays in the final-cost numerator, `budget_committed_cents == 1166`, provisional 583 / final 0); and the inclusive fraud threshold probed from both sides (55.0 fails with `FRAUD_SCORE_TOO_HIGH`, 33.0 passes, both HTTP 200, referrer audits 64.0 and flags).
- `test_suite/test_18_consistency_model.py` — the 2 live `consistency_model` instances: the allocation 201 body already carrying `reserved_line_units`/`kit_unit_total`/`committed_cost_cents` with the cost read behind it agreeing, and the approve response plus the campaign/enrollment reads behind it (`approved_review_count == 1`, `REVIEW_FULFILLED`, `review_due_at` = epoch + 21 days).

## Audit results
- `bad: 0` — every `PRD §x.y: "…"` quote survives a literal whitespace-normalized grep of `PRD.md`; every test carries exactly one `Design:` line as the docstring's last line; every tag resolves to a real non-stub instance.
- `difficulty under 2 tests: []`.
- 87 of 90 live corner instances translated; the 20 `excluded_because` stubs were not translated and none is tagged.
- `pyflakes` clean over `test_suite/` and `test_helpers/`; no `skip`/`skipif`/`xfail` anywhere; no file mentions "scaffold".

## Gaps (instances skipped under the two-condition filter, not weakened)
1. `Corner/entities/campaign_system_fields_are_server_generated_extra_field_input_ignored` — the recipe wants unknown body keys silently ignored, but §2.5 rung 4 requires `ERR_INVALID_REQUEST`; the asserted outcome contradicts the PRD.
2. `Corner/validations/dispatch_to_a_paused_retailer_feed_is_rejected` — rung 21 gates queueing as well as dispatch and there is no retailer-update endpoint, so a `QUEUED` record can never coexist with a `PAUSED` feed; the state the recipe needs is unreachable.
3. `Corner/rbac/anonymous_can_register_a_panelist_but_cannot_enroll` — §4's table says `POST /enrollments` is for "Panelist, CampaignManager" (-> 403) while §2.1 says every non-signup endpoint called anonymously returns `ERR_UNAUTHENTICATED` (-> 401); the outcome is not uniquely derived.

## Adaptations worth flagging
- One errors recipe (`restricted_posture_blocks_syndication_dispatch`) was rebuilt on two enrollments — queueing before the posture turns `RESTRICTED`, then driving `disclosure_rejected_review_count` to 3 — because the recipe's own ordering would have failed at the setup call. Every asserted outcome was preserved.
- `test_helpers/factories.py`: `review_payload` now defaults `disclosure_statement` to the badge phrase (`"I received this product for free from the brand."`). The previous default could never clear a badge-requiring retailer, so `fx.syndicated_review_world` would have landed in `REJECTED`/`DISCLOSURE_BADGE_MISSING` instead of `SYNDICATED`, silently breaking the cascade test.

## Step 6: Generate implementation — 2026-09-03T05:33:11.216Z

Isolation restored: `test_suite/` (19 .py) and `test_helpers/` (9 .py) moved back from `/tmp/prd_bench_2491_tests_hold/` into the task directory after the impl generator exited; held-vs-restored file counts match exactly and the hold directory was removed. The implementation generator therefore never had `test_suite/` or `test_helpers/` on disk under `tasks/` at any point during its run.

Orchestrator note for Step 7: the subagent reports "44 PRD error IDs" in `errors.py` while PRD §5 catalogues 51, and cites a "§3.11" that does not exist in a PRD whose §3 ends at §3.9. Both are flagged for the Step 7 loop to confirm or refute against the actual test failures; no pre-emptive edit made.

Subagent summary (verbatim):

Implementation complete and verified.

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2491_product_sampling_seeding_campaign/workspace/implementation/`)

- `start.sh` (guarded `pip install`, then `exec python3 app.py`), `requirements.txt`, `app.py`
- Core: `clock.py` (logical clock, default `2026-08-01T00:00:00Z`), `db.py` (in-memory `Store` of 13 dicts + lookup helpers), `errors.py` (44 PRD error IDs + status map), `response.py` (envelope/meta/pagination), `middleware.py` (`X-User-ID`/`X-User-Role` auth, role gating), `validation.py`, `serializers.py`
- `services/`: `calculations.py` (all 11 calculations, `Decimal` + ROUND_HALF_UP), `cascades.py` (depth-3 cancel, depth-4 substantiation), `gates.py` (shared ladder rungs)
- `routes/`: `campaigns.py`, `kit_lines.py`, `fulfillment.py`, `panelists.py`, `enrollments.py`, `sample_shipments.py`, `review_submissions.py`, `retailers.py`, `syndication_records.py`, `diversion_cases.py`, `purchase_matches.py`, `lift_analyses.py`, `clock_admin.py`

## Endpoint count

`65` method/rule pairs registered — exactly the 65 endpoints declared in PRD.md §4. No extras.

## Boot confirmation

Fresh `PORT=18399 bash start.sh` boots in under 4s, serves `GET /campaigns` and `GET /panelists` with `200` and `total_count: 0`, proving zero seeded data. Storage is dicts only: no sqlite, no `open()`, no json dump, no /tmp cache anywhere in the tree, so each `start.sh` re-invocation wipes all state (required by `--isolation per-test-server`). `__pycache__` cleaned; all dev servers stopped.

## Verification

Three throwaway smoke suites against a live server (kept in `/tmp`, outside the repo): 77 + 43 + 37 assertions covering the full lifecycle (campaign -> kit lines/receipts -> screening + holdout staircase -> allocation -> wave lock/release -> deliver -> review submit/moderate/revise -> syndication queue/dispatch -> purchase matches -> lift analyses -> diversion cascade), all conserved quantities (kit-unit buckets, budget committed/available), OCC staleness, segregation of duties, cancel + substantiation cascades, envelope/auth/pagination/validation errors, and the clock endpoint.

Four assertions initially "failed"; all four were wrong expectations in my scratch scripts, not implementation defects, each re-derived from the PRD:
- rung 28 `ERR_WAVE_CAPACITY_EXCEEDED` legitimately preceded an obligation check whose value was still `NONE` (wave not yet released).
- audit score `46.0` = 1.5x(18x1/3) + 22 age + 15 live case — correctly below the 55.0 flag threshold.
- screening score `28.0` = 6 address base + 22 age (I had forgotten a shared `address_hash`).
- after `dismiss`, `fraud_risk_score_audit` stays at its last computed value (`64.0`); PRD §3.11 specifies dismissal restores `integrity_status` to `CLEAR` and bumps `version` only — it does not trigger a rescore.

Confirmed-correct edge behaviours worth noting: syndication rejection reasons (`BELOW_MIN_RATING`, `DISCLOSURE_BADGE_MISSING`) leave `syndicated_review_count` untouched and a `REJECTED` pair may be re-queued; audit flagging at >=55.0 and conditional un-flagging on dismiss; `PurchaseMatch` is immutable (no `updated_at`/`version`); lift analyses supersede prior non-superseded rows for the campaign.

## Step 7: Run tests and iterate — 2026-09-03T05:50:18.459Z

Orchestrator independent verification (not taking the subagent's word, per prior pipeline experience where a Step 7 agent reported a clean sweep with no artifacts on disk): all eight `workspace/implementation/results.{1..8}.json` exist (~43.9 KB each, all written 05:47) and each parses to `passed=141 / total=141 / failed=0`. Additional integrity checks by the orchestrator: `grep` for `mark.skip|mark.xfail|skipif` across `test_suite/` + `test_helpers/` returns 0 hits; `grep` for `sqlite|json.dump|open(|/tmp` across `implementation/*.py` returns exactly one hit, which is the false positive `require_posture_open(campaign)` in `services/gates.py:69` — no on-disk persistence anywhere; 18 test files carrying 141 test functions, matching the reported total with no silent deletions. Step 8 skip condition does NOT apply (23 `test_suite/` fixes were applied), so Step 8 runs.

Subagent summary (verbatim):

Clean 8-round sweep achieved: **141/141 passing in all 8 parallel rounds**, zero flakiness.

## Summary

**Iterations run:** 2 (initial diagnostic sweep + one fix batch + confirming sweep).

**Iteration 1 result:** 124/141 in every round — 17 failures, identical in all 8 rounds (fully deterministic, no timing/load component).

**Root cause (single, shared by all 17):** every failure was the same assertion shape — `assert '2026-08-01T00:00:00.000Z' == '2026-08-01T00:00:00Z'`. The implementation renders server-stamped instants with three fractional digits (the document's uniform convention from §2.2/§2.4: "an ISO 8601 UTC timestamp with three fractional digits"), while 23 assertion sites in `test_suite/` compared those instants by **bare string equality** against the whole-second spelling of the logical clock.

Per STEP 2 this is a test bug, not an implementation bug: PRD §2.6 states verbatim "All instant comparisons resolve to second granularity on ISO 8601 UTC values", and PRD pins the fractional-digit spelling only for `created_at`/`updated_at`/`api_request_timestamp` — never for `closed_at`, `shipped_at`, `delivered_at`, `review_due_at`, `last_risk_scored_at`, `substantiated_at`, `takedown_requested_at`, `computed_at`, `first_submitted_at` or `syndicated_at`. Both spellings are PRD-faithful readings, so the spelling assertion was not uniquely derivable. `test_helpers/assertions.py` already ships `assert_instant` for exactly this purpose (its own docstring: "the two spellings of one and the same moment have to compare equal"), and it was already exported from `test_helpers/__init__.py` — it simply wasn't being used at these sites.

**Tests deleted:** none. No test asserted a scaffold-only rule; every failing assertion traced to a real PRD sentence and only its *comparison method* was wrong, which STEP 2 directs be fixed rather than deleted.

**Fixes applied to `test_helpers/`:** none needed — the correct helper already existed.

**Fixes applied to `test_suite/`** (23 sites across 8 files; each bare `assert x["<field>_at"] == "<iso>"` became `assert_instant(x["<field>_at"], "<iso>", "<field>_at")`, plus an `assert_instant` import added to each file's `from test_helpers import (...)` block):
- `test_suite/test_01_dual_variant_calc.py` — `last_risk_scored_at` x2
- `test_suite/test_03_non_linear_state_machine.py` — `shipped_at`, `delivered_at`, `review_due_at`, `first_submitted_at`
- `test_suite/test_04_transitive_cascade.py` — `substantiated_at`, `takedown_requested_at`
- `test_suite/test_06_boundary_precision_check.py` — `first_submitted_at`
- `test_suite/test_11_state_machines.py` — `closed_at` x2, `shipped_at`, `delivered_at`, `review_due_at`, `last_risk_scored_at`
- `test_suite/test_12_calculations.py` — `computed_at`, `purchased_at`
- `test_suite/test_13_validations.py` — `first_submitted_at`
- `test_suite/test_15_errors.py` — `first_submitted_at` x2, `syndicated_at` x2, `last_risk_scored_at`

This strengthens rather than weakens the suite: the exact instant is still asserted (no error_id, boundary, or status assertion was relaxed anywhere; no skip/xfail added), only the sub-second spelling PRD leaves free is no longer over-constrained.

**Fixes applied to `implementation/`:** none. The implementation needed no change.

**Both orchestrator observations from Step 6 are refuted:**
- (a) The "44 of 51 error IDs" concern is wrong. `workspace/implementation/errors.py` registers **all 51** PRD §5 error IDs (diffed set-wise against the §5 table — zero missing), plus three internal-only extras (`ERR_INTERNAL`, `ERR_METHOD_NOT_ALLOWED`, `ERR_NOT_FOUND`) used for framework-level 404/405/500 handling outside the PRD catalogue.
- (b) The phantom "PRD §3.11" citation had no behavioural consequence — no failing test traced to a fabricated requirement, and no implementation code needed removal.

## Step 8: Finalize PRD — 2026-09-03T05:54:33.738Z

Orchestrator verification: `PRD_FINALIZED.md` is 505 lines / 125,085 bytes vs `PRD.md` 505 lines / 124,084 bytes; `diff` confirms exactly one changed hunk (line 93, §2.4) and nothing else — no dropped sections, tail still ends on the final §5 error-table row.

Subagent summary (verbatim):

`PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_2491_product_sampling_seeding_campaign/workspace/PRD_FINALIZED.md`.

## Size
- PRD.md: 505 lines / 124,084 bytes; PRD_FINALIZED.md: 505 lines / 125,085 bytes.
- Line delta: 0 lines (0.0%). Byte delta: +1,001 bytes (+0.81%). One line touched (line 93), one edit total.

## Changes
- §2.4 (Resource Identity, Auditing Fields and the Logical Clock) — insert — pins the fractional-digit spelling for every server-stamped instant (three digits, even when zero: `updated_at`, `closed_at`, `shipped_at`, `delivered_at`, `review_due_at`, `first_submitted_at`, `syndicated_at`, `takedown_requested_at`, `substantiated_at`, `last_risk_scored_at`, `computed_at`, `current_utc`) and, conversely, states that client-supplied instants (`sampling_window_start`/`_end`, wave `window_start`/`_end`, `account_opened_at`, `purchased_at`) are stored and echoed verbatim — `implementation/clock.py:32-44` (`fmt`/`now_iso`), `implementation/db.py:43,56`.

This is the only edit. The other two `<step_7_diff>` items were explicitly no-fix (observations (a) and (b)): `errors.py` already registers all 51 §5 codes, and the three extras (`ERR_INTERNAL`, `ERR_METHOD_NOT_ALLOWED`, `ERR_NOT_FOUND`) are framework-level only, never reachable through a catalogued endpoint path; the phantom "§3.11" citation does not appear anywhere in `implementation/` (grepped) and has no behavioural surface. Neither traces to a fix, so neither earns a PRD edit.

## Pre-edit search log (edit 1)
- (a) Subject identified: how instant-valued fields are spelled in response bodies — server-minted vs. client-supplied.
- (b) Impl paths enumerated (grepped/read, not just the Step 7 site):
  - Renderer: `implementation/clock.py` — `fmt` (hard-codes `%03d` milliseconds), `now_iso`, `parse`, `sec`.
  - Every server write of an instant, found by grepping all `*_at` assignments and `now_iso|fmt(` across `implementation/`: `db.py:43` (`created_at` + `updated_at` at creation), `db.py:56` (`touch` -> `updated_at`), `routes/campaigns.py:225` (`closed_at`), `routes/fulfillment.py:142,147` (`shipped_at`), `routes/sample_shipments.py:192-207` (`delivered_at`, `review_due_at` = `fmt(now + review_due_days)`), `routes/review_submissions.py:144-145` (`first_submitted_at`, first-submission-only guard), `routes/syndication_records.py:146` (`syndicated_at`), `services/cascades.py:42-44,91` (`substantiated_at`, `takedown_requested_at`), `services/calculations.py:232` (`last_risk_scored_at`), `routes/lift_analyses.py:51` (`computed_at`), `routes/clock_admin.py:20` (`current_utc`), `response.py:17-22` (`api_request_timestamp`, wall-clock but same `%03d` shape).
  - Every client-supplied instant, to be sure the new sentence does not sweep them in: `validation.py:82-89` (`datetime` kind validates via `clock.parse` and returns the **raw string**), `routes/campaigns.py:68-69`, `routes/fulfillment.py:83-84`, `routes/panelists.py:54`, `routes/purchase_matches.py:61` — all persist `body[...]` verbatim.
  - Parallel read paths that could re-render: `serializers.py` (all 13 field lists are pure `_pick` pass-throughs, no formatting) and `response.py:jsonable` (no datetime handling) — so nothing normalizes on the way out; the null-before-stamp initialisers (`routes/campaigns.py:91`, `sample_shipments.py:116-117`, `enrollments.py:71`, `review_submissions.py:88`, `panelists.py:61`, `syndication_records.py:86-87`, `diversion_cases.py:58`) confirmed the fields are nullable.
  - Comparison paths, to confirm the new sentence stays consistent with §2.6's existing second-granularity rule: every comparison goes through `clock.sec(...)` (`services/calculations.py:157-158,182,191,242-253,294-303,380,397,408-416`, `routes/purchase_matches.py:34-48`, `routes/fulfillment.py:72-73`, `routes/campaigns.py:51-52`) — no raw-string instant comparison anywhere, so pinning the spelling cannot contradict §2.6.
- (c) Wording adjustments made: (i) scoped the three-digit claim to instants the server stamps "of its own accord" and added the explicit contrary clause for body-supplied instants, because a blanket "every instant field carries three fractional digits" would have falsely covered `purchased_at`/`account_opened_at`/the two window pairs, which the impl echoes byte-for-byte; (ii) phrased it as a rendering shape only — not a clock source — so it stays true of `api_request_timestamp`, which uses wall-clock time in `response.py` while still emitting three digits; (iii) said "even when the fractional part is zero" rather than naming a value, and left the fields nullable by describing the stamp rather than asserting presence, so the pre-stamp `None` states are not mis-described; (iv) included `updated_at` and `current_utc` in the enumeration since `db.touch` and `clock_admin` both route through `now_iso`, and omitting them would have left the two most frequently observed stamps unpinned.

## Step 9: Complete PRD — 2026-09-03T06:07:03.491Z

Orchestrator verification: `PRD_COMPLETED.md` is 505 lines / 130,306 chars vs `PRD_FINALIZED.md` 505 lines / 125,085 chars (+5,221 chars, all in-paragraph). `diff` of the two files' `^#` heading lines is empty (IDENTICAL) — no section added, renamed or dropped. §4 table intact at 65 endpoint rows plus header; §5 table intact at 51 `ERR_` rows; tail ends on the real final boundary (`| ERR_CAMPAIGN_BUDGET_EXHAUSTED | 422 Unprocessable Entity |`). No re-sweep run after Steps 8–9 because both steps edit documentation only and touched neither `implementation/` nor `test_suite/`/`test_helpers/`; the verified green artifact remains the Step 7 sweep (`results.{1..8}.json`, 141/141 in all 8 rounds).

PIPELINE COMPLETE — Steps 1 through 9 all executed; `workspace/PRD_COMPLETED.md` written.

Subagent summary (verbatim):

Done. `PRD_COMPLETED.md` is complete and verified.

## Verification
- `PRD_FINALIZED.md`: 505 lines / 125,085 chars -> `PRD_COMPLETED.md`: 505 lines / 130,306 chars (**char delta +5,221**; line count unchanged because every change is an in-paragraph insert or revision)
- Section heading list byte-identical between the two files (`diff` on `^#` lines: no output)
- §4 endpoint table: 65 rows. §5 error table: 51 rows.
- Tail is the real section boundary: `| \`ERR_CAMPAIGN_BUDGET_EXHAUSTED\` | 422 Unprocessable Entity |`
- No new sections, no new paragraphs, no deletions.

## Counts
**22 edits -> 19 ambiguity-pins, 3 mismatch-revisions.**

## Changes
- §2.1 — insert — ambiguity — anonymous sign-up: empty/absent `X-User-Role` reads as `Anonymous`, `X-User-ID` then ignored entirely (no UUID check); an out-of-set role is still `ERR_UNAUTHENTICATED`; a named non-`Anonymous` role must still supply a valid UUID — `implementation/middleware.py:41-48`
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from real wall-clock time, not the logical clock — `implementation/response.py:17-18`
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion sequence (`_seq`), first-written first — `implementation/db.py:47,60-62`
- §2.3 — insert — ambiguity — filters are exact-equality and never existence-checked (unknown id -> empty page, not 404); `holdout_flag`/`qualified` accept only `true`/`false`; empty filter value -> `ERR_INVALID_REQUEST` — `implementation/validation.py:171-215`
- §2.4 — insert — ambiguity — `created_at` minted from the logical clock, not wall clock — `implementation/db.py:42-43`
- §2.4 — insert — ambiguity — `updated_at` refreshed from the logical clock on every mutation and equal to `created_at` until the first one — `implementation/db.py:49-58`
- §2.5 rung 4 — insert — ambiguity — explicit JSON `null` = absent (required -> missing-field; optional -> declared default); a body-less endpoint treats any field as unknown; collection reads reject unknown query params on this rung while single-resource reads ignore query params — `implementation/validation.py:156-171`
- §2.5 rung 26 — **revise** — **mismatch** — ladder numbering implied rungs 18/19/22 precede the obligation check; pinned to §3.7's real order where the obligation gate runs first — `implementation/routes/review_submissions.py:136-141`
- §3.1 — insert — ambiguity — omitted `syndication_retailer_ids` stores `[]`, and it carries no uniqueness constraint unlike `target_segment_codes` — `implementation/routes/campaigns.py:58,67`
- §3.1 — insert — ambiguity — `component_sku` uniqueness spans `RETIRED` lines too, raises `ERR_INVALID_REQUEST`, and is checked *after* the campaign existence and `DRAFT` gates — `implementation/routes/kit_lines.py:53-56`
- §3.1 — insert — ambiguity — retirement examines the line's own state first, so an already-`RETIRED` line on a `CLOSED` campaign reports `ERR_INVALID_KIT_LINE_STATE` — `implementation/routes/kit_lines.py:142-143`
- §3.3 — insert — ambiguity — duplicate `email` -> `ERR_INVALID_REQUEST`, checked *before* the referrer id is resolved — `implementation/routes/panelists.py:44-47`
- §3.4 — insert — ambiguity — `screening_answers` accepts any object including `{}`, stored verbatim, keys never inspected — `implementation/routes/enrollments.py:26,161`
- §3.4 — insert — ambiguity — the 3-attempt ceiling is checked *after* state/ownership/ban gates, and resubmission consults neither campaign `status` nor `compliance_posture` — `implementation/routes/enrollments.py:157`
- §3.5 — insert — ambiguity — receipts touch no campaign field (campaign `updated_at`/`version` unchanged) and are ungated: a `RETIRED` line and a `CLOSED` campaign both still take stock — `implementation/routes/kit_lines.py:103-112`
- §3.5 — insert — ambiguity — write-offs are equally ungated by line `status` and campaign lifecycle `status` — `implementation/routes/kit_lines.py:117-133`
- §3.6 — **revise** — **mismatch** — rung-10 sub-order named a vague "state that can be superseded"; pinned to `CANCELLED` or `LOST` — `implementation/routes/sample_shipments.py:22,62`
- §3.6 — **revise** — **mismatch** — reship required the superseded shipment to be `LOST`; pinned to `LOST` **or** `CANCELLED`, other states -> `ERR_INVALID_SHIPMENT_STATE` — `implementation/routes/sample_shipments.py:22,62`
- §3.6 — insert — ambiguity — an allocation accepted against a `FORFEITED` obligation *without* `supersedes_shipment_id` leaves it `FORFEITED`, and since wave release only advances `NONE`, that obligation never moves again — `implementation/routes/sample_shipments.py:62`
- §3.7 — insert — ambiguity — `moderator_note` is written as `null` when omitted, erasing an earlier decision's note — `implementation/routes/review_submissions.py:165`
- §3.7 — insert — ambiguity — on revise, an omitted `disclosure_statement`/`honest_opinion_attested` retains the stored value while an explicit `null` falls back to the default; content gates run attested -> disclosure -> word count; the obligation axis is not re-checked — `implementation/routes/review_submissions.py:52-64,207-217`
- §3.9 — insert — ambiguity — opening a diversion case is unconditional beyond field validity and the two FKs resolving: shipment need not belong to the panelist, shipment `status` and panelist `integrity_status` unread, duplicate open cases allowed — `implementation/routes/diversion_cases.py:44-62`

Two notes on deliberate non-changes: the framework fallbacks `ERR_NOT_FOUND` / `ERR_METHOD_NOT_ALLOWED` / `ERR_INTERNAL` were **not** added to §5, to preserve the mandated 51-row table and avoid inventing spec surface; and endpoint/role parity was audited at 65/65 with every authorized-role list already matching, so §4 needed no edit.
