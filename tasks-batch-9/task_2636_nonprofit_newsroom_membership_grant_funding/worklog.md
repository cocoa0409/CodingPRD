# Worklog — task_2636_nonprofit_newsroom_membership_grant_funding

## Step 1: Create task directory — 2026-09-03T23:02:31.241Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2636_nonprofit_newsroom_membership_grant_funding` and its `workspace/` subdirectory. Index 2636 was pre-assigned by the orchestrating command; no scan of `./tasks/` was performed and no index was auto-allocated.

## Step 2: Generate scaffold — 2026-09-04T01:12:50.899Z

All three files are complete and the linter is clean.

## Deliverables

| File | Lines |
|---|---|
| `/home/ubuntu/github/CodingPRD/tasks/task_2636_nonprofit_newsroom_membership_grant_funding/SCAFFOLD.yaml` | 3458 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2636_nonprofit_newsroom_membership_grant_funding/SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 1544 |
| `/home/ubuntu/github/CodingPRD/tasks/task_2636_nonprofit_newsroom_membership_grant_funding/SCAFFOLD_CORNER_DESIGN.yaml` | 4266 |

## SCAFFOLD.yaml contents (§1.0–§1.7 only; no design keys present)
- 13 entities, 11 state machines, 2 concurrency rules, 11 calculations, 55 validations, **67 endpoints**, 68 errors, 5 roles
- `complexity_profile`: `beyond_expert`, compliance_audit / multi_party_negotiation, flat topology, cyclic state machines, `segregation_of_duties` role model, `immediate` consistency, layers = dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency

## Design index files
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8): **18 instances**, single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9): **90 instances** (75 full `test_recipe` + 15 `excluded_because` stubs), single top-level key `scaffold_corner_design`, nine `- section:` groups — Entities 12, State Machines 10, Calculations 8, Validations 38, Endpoints 6, Errors 1, RBAC 7, Cross-Cutting Complexity Layers 6, Consistency Model 2

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2636_nonprofit_newsroom_membership_grant_funding/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2636_nonprofit_newsroom_membership_grant_funding/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2636_nonprofit_newsroom_membership_grant_funding/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    67
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     75
  Calls scanned (§1.8+§1.9):  774

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Extra verifications run beyond lint
- **Error coverage:** all 68 catalog ids appear as an asserted outcome somewhere across the two design files (0 missing).
- **Name uniqueness:** no duplicate instance names across the union of both files; all 15 stub `difficulty_instance` refs resolve to one of the 18 §1.8 names.
- **Forbidden concurrency vocabulary:** zero hits for "simultaneously", "at the same time", "concurrently submitted", "in parallel", "first-writer-wins", "race winner/loser", "two clients race", "arriving together".

## Two corrections made while finishing the corner file
- An Endpoints instance had claimed `CANCEL` was reachable from `GRACE`; the Member machine only declares `ACTIVE -> CANCELLED`, so it was rewritten as `ep_member_cancel_action_clears_the_renewal_schedule_and_locks_the_row` (cancel from ACTIVE, dates nulled, then `REINSTATE` → `ERR_TERMINAL_STATE`).
- The transparency-report read was switched off the entity-backed `Member` role (an arbitrary `X-User-ID` would not resolve to a Member row) to `BoardOversight`.
- The planned "cultivation-locked tier change" assertion was dropped from the rate-threshold instance: `cultivation_locked == false` is a bare transition precondition with no dedicated error id, so the instance now asserts only the cumulative latch boundary (494999 → 497499 → exactly 500000).

## Step 3: Copy shared files — 2026-09-04T01:13:08.746Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T01:30:06.448Z

PRD generated and verified at `/home/ubuntu/github/CodingPRD/tasks/task_2636_nonprofit_newsroom_membership_grant_funding/workspace/PRD.md`.

**Line count: 507.** Built with nine chunked heredoc appends (`cat >> PRD.md <<'PRDEOF'`), never a single giant Write. The document ends at a real boundary — the final line is the last data row of the §5 error table (`ERR_UNSETTLED_CONTRIBUTIONS | 409`), not mid-sentence.

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 Role-Based Access Control, 2.2 API Response Structure (byte-identical to `section-2.2-response-structure.md`, verified by exact substring match), 2.3 Pagination, 2.4 Common Resource Properties and the Logical Clock, 2.5 Segregation of Duties, 2.6 Amounts/Basis Points/Rounding, 2.7 Optimistic Concurrency, 2.8 Derived Fields and Cascades, 2.9 Validation Ordering (20-step ladder), 2.10 Sub-Resource Reads and Reverse Reachability, 2.11 The Independence Firewall as a Precondition on Money
- §3 Business Logic & Workflows — 3.1 Fiscal Year, 3.2 Membership Tiers and Benefit Valuation, 3.3 Member Lifecycle, 3.4 Coverage Areas / Funder Cultivation / Firewall, 3.5 Disclosures and Influence Contacts, 3.6 Major Gift Cultivation, 3.7 Grant Pipeline (award, release waterfall, reporting, delinquency), 3.8 Collaborations and Cost Conservation, 3.9 Contribution Ledger (two dimensions, HHI, reserve posture)
- §4 API Endpoint Definitions
- §5 Error Code Catalogue

**Coverage verified mechanically** (inventory extracted from SCAFFOLD.yaml into `/tmp/req_tokens.json`, then matched against the document):
- Endpoints: 67/67 present as `| METHOD | \`path\` |` rows; §4 table has 69 lines = header + separator + 67 rows, uniformly 4 columns.
- Errors: 68/68 in the §5 table (2 columns, 70 lines = header + separator + 68), and 68/68 also appear in §1–§4 prose — zero errors exist only in the table.
- Contract 1 field-name coverage: 140/140 entity field names and 88/88 endpoint input identifiers appear verbatim in backticks. 0 missing.
- Contract 2 rule coverage: all 55 validations (every error id sited with its trigger and ordering), all 11 calculations with pinned evaluation orders and both dual-variant pairs (risk self-attested vs audited; diversification recognized vs pipeline), all 8 state machines — every state name and every enum value from every `constraints: one of {...}` appears in backticks (0 missing) — both `concurrency_rules` entries with write operation + `expected_funder_version`/`expected_member_version` + `ERR_STALE_FUNDER_VERSION`/`ERR_STALE_MEMBER_VERSION` + 412, and all cascades (funder-restriction 5-hop, report-delinquency 4-hop, refund giving-ledger 4-hop). Every numeric constant from every calculation now appears verbatim (0 missing) — I fixed two that had been written only in dollars by adding `1000000 cents` and `2500000 cents` alongside them.
- Contract 3 §3 path purity: 0 violations. No backtick token in §3 starts with `/`, is a bare HTTP method, or combines method+path; a raw-text scan for unquoted `METHOD /path` and for any of the 15 resource path roots inside §3 also returned empty. Operations are named by state pair, role+verb, or capability.
- No fuzzy quantifiers (`approximately`, `roughly`, `conservatively`, `about`, `around`, `etc.`) anywhere in the document.

**Scaffold inconsistencies I resolved** (choices held stable across the document): `cultivation_locked` follows the calculation (`= is_major_donor`, latching) rather than the entity-description variant; `grace_expires_at` uses the tier's `grace_period_days` from `next_renewal_date`; board ratification of an offer not requiring it maps to `ERR_INVALID_STATE`; an `occurred_at` after the logical clock maps to `ERR_INVALID_REQUEST`; the `ERR_CONCENTRATION_LIMIT_EXCEEDED` mentioned in a field description is not in the error catalogue, so I followed the validations table (`ERR_CONCENTRATION_BOARD_REVIEW_REQUIRED` at lock, `ERR_RESERVE_FLOOR_BREACH` at close).

Both withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced, and no sibling task directory was read.

**Orchestrator truncation check:** independently confirmed — 507 lines, tail ends at the complete final row of the §5 catalogue table, section headings run §1 → §5 in order with no gaps. Not truncated; no regeneration needed.

## Step 6: Generate implementation — 2026-09-04T02:14:00.000Z

The implementation is complete and verified.

## Files written
`/home/ubuntu/github/CodingPRD/tasks/task_2636_nonprofit_newsroom_membership_grant_funding/workspace/implementation/`

| File | Lines | Role |
|---|---|---|
| `core.py` | 628 | in-memory store, logical clock, response envelope, 68-entry error catalogue, auth/RBAC, validators, pagination |
| `routes_grants.py` | 571 | grant pipeline: proposal, award, release, reports (14 endpoints) |
| `derive.py` | 424 | all cascade recomputation (period sustainability, funder, member, proposal compliance, collaboration split) |
| `calc.py` | 413 | the 11 named calculations + enum tuples + thresholds |
| `routes_firewall.py` | 399 | coverage areas, funders, disclosures, influence contacts (15) |
| `routes_collab.py` | 297 | collaborations, partners, lifecycle (8) |
| `routes_membership.py` | 295 | tiers, members, tier-change, daily sweep (9) |
| `routes_contributions.py` | 281 | contributions, settle, refund, acknowledge (6) |
| `routes_gifts.py` | 252 | major-gift cultivation (7) |
| `routes_fiscal.py` | 237 | fiscal periods, clock, sustainability (8) |
| `guards.py` | 120 | shared ladder guards keyed to validation priorities |
| `app.py` | 57 | app factory, blueprint registration, error handlers |
| `start.sh` | (398 B, +x) | reads `$PORT`, binds 0.0.0.0, foreground `exec python3 app.py` |
| `requirements.txt` | 1 | `flask>=2.0` |

Total 3,974 lines of Python. All 12 modules pass `python3 -m py_compile`.

## Endpoints
**67 of 67** implemented. Flask `url_map` enumeration yields exactly 67 GET/POST routes, matching the PRD's declared set one-for-one.

## Constraint compliance
Storage is in-memory dicts only (no SQLite, no disk, no `/tmp`). The store boots completely empty — nothing seeded, preloaded, or hardcoded; the logical clock starts at exactly `2026-08-01T00:00:00Z` on every fresh process. Nothing under `test_helpers/` or `test_suite/` was read or written, and no sibling task directory was touched.

## Smoke test
Launched via `PORT=18737 bash start.sh`, exercised, then killed by recorded PID only (`pkill -P $PID; kill $PID`), port confirmed free. No broad `pkill` was used at any point.

- **Happy path (33 assertions, all OK)** on a single fresh boot: gift netting fee 150000 / net 5850000 / ratification required on a 6,000,000-cent restricted offer; the cascade contribution discoverable only via `GET /contributions?gift_offer_id=`; award ledger 9999999/0/9999999/0 with one SEMIANNUAL obligation (2026-09-01 -> 2027-02-28, due 2027-04-14); release 5000000 leaving 4999999 unreleased; membership qpq 100 / deductible 1900; PENDING->ACTIVE on settlement with receipt `RCPT-000001`; largest-remainder split 333/333/334 = 1000 with remainder ranks 3 and 1; PIPELINE sustainability projection (HHI 5341, posture WATCH, cap 6000 bps); a daily sweep that moved a member GRACE->LAPSED, took a report OVERDUE and suspended the proposal in one pass.
- **Negative paths:** 401 (missing headers, unknown role), 403 `ERR_UNAUTHORIZED`, 404 FK resolution ahead of shape and bps-range checks, 422 for bad enums / date range / `limit=0` / `limit=101`, correct pagination `meta`, 404 on an unknown route, and 422 `ERR_CLOCK_REWIND`. The one line printing `FAIL` is my scratch script asserting 409 for the rewind; PRD §5 line 489 specifies **422**, so the server is correct and the expectation was wrong.

## Defect fixed this session
`core.ERROR_STATUS` keyed the partner not-found error as `ERR_COLLABORATION_PARTNER_NOT_FOUND`, while the PRD ladder (§2.9 item 3) and catalogue both name it `ERR_PARTNER_NOT_FOUND`. Because `routes_collab.py` already raised the correct PRD id, the missing key made `ApiError` fall back to HTTP 422 instead of 404 on `GET /collaboration-partners/{id}` and `POST /collaboration-partners/{id}/withdraw`. Renamed the key; a live request now returns `404 ERR_PARTNER_NOT_FOUND`.

A full cross-check of the PRD §5 catalogue against the implementation now reports 68 vs 68 entries with **zero** missing, extra, or status-mismatched ids (distribution 409x38, 404x13, 422x11, 403x3, 412x2, 401x1).

## Step 5: Generate unit tests — 2026-09-04T03:18:28.225Z

All 20 test files plus infrastructure are complete and validated. Final state:

## Files written (task root, nothing under `workspace/`)

`/home/ubuntu/github/CodingPRD/tasks/task_2636_nonprofit_newsroom_membership_grant_funding/test_helpers/` — 2,581 lines across 9 files (`__init__.py` 1.1K, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py` 29.8K, `test_users.py`, `types.py`).

`.../test_suite/` — 9,239 lines total: `conftest.py` 78; queue A `test_01` 343 / `test_02` 251 / `test_03` 273 / `test_04` 311 / `test_05` 242 / `test_06` 255 / `test_07` 380 / `test_08` 388 / `test_09` 431; queue B `test_10` 480 / `test_11` 565 / `test_12` 681 / `test_13` 848 / `test_14` 696 / `test_15` 415 / `test_16` 542 / `test_17` 477 / `test_18` 425 / `test_19` 521 / `test_20_corner_layers_and_consistency.py` 636 (written last: 16 tests over the 4 non-stub Cross-Cutting layers and the 1 non-stub Consistency instance).

## Tests and coverage

- **257 tests**, every one carrying exactly one `Design:` tag (81 `Difficulty/...`, 176 `Corner/...`); per-file test count equals per-file tag count in all 20 files; all 93 tag names resolve to real `name:` entries in the two design yamls.
- Queue A (§1.8): **18 of 18** non-stub instances, >=2 tests each.
- Queue B (§1.9): **75 of 75** non-stub instances — Entities 12/12, State Machines 10/10, Calculations 8/8, Validations 27/27, Endpoints 5/5, Errors 1/1, RBAC 7/7, Cross-Cutting 4/4, Consistency 1/1.

## Skipped

No instance failed the PRD-first filter. The only uncovered items are the **15 yaml stubs carrying `excluded_because`** (11 Validations, 1 Endpoints — `ep_sustainability_read_diverges_between_the_recognized_and_pipeline_bases`, 2 Cross-Cutting — `layer_influence_contact_cascade_reaches_five_levels` / `layer_dual_variant_revenue_index_produces_two_answers`, 1 Consistency — `cm_sweep_derived_penalties_are_visible_in_the_sweep_response`), each already covered by the §1.8 instance the stub names.

Assertion-level deviations where the yaml contradicted the PRD (instance still covered, PRD followed):
- `cm_settlement_...`: yaml's empty-period `HEALTHY`/cap 10000 -> PRD gives `WATCH`/6000 (reserve 500000 < 600000 target); yaml's post-settlement `top_source_share_bps 10000` / `reserve_months_target 5` / `operating_reserve_target_cents 1000000` -> PRD excludes members from the institutional top-source measure, so top share is 0, target 4, operating target 800000.
- `val_delinquent_...` (test_17): PRD's reinstatement asymmetry gives released 0 / unreleased 350001 / returned 0, not the yaml's figures.
- `ep_funder_list_...` (test_18): dropped the `funder_type` filter assertion (PRD documents only FK and status filters for `GET /funders`).
- Standing substitutions applied throughout: `quid_pro_quo_amount_cents`/`tax_deductible_amount_cents` -> `quid_pro_quo_cents`/`deductible_cents`, `UNDESIGNATED` -> `UNRESTRICTED`, non-PRD `fulfillment_type` values remapped, yaml statuses contradicting §5 replaced by the map-checked `validate_error`.

## Verification run

`ast.parse` over all 30 files passes; `pyflakes` reports nothing but the conventional `'pytest' imported but unused` (two stale imports in test_03/test_05 removed in this pass); all **257 `PRD: "..."` citations verified verbatim** against `workspace/PRD.md` after em-dash/arrow normalization; `find workspace -name test_helpers -o -name test_suite` returns nothing (`workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation`).

**Orchestrator layout check:** confirmed `test_helpers/` and `test_suite/` sit at the task root and neither exists under `workspace/`; `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/`. 21 files in `test_suite/`.

## Step 7: Run tests and iterate — 2026-09-04T04:14:00.000Z

Clean sweep: 257/257 in all 8 rounds.

## Summary

**Iterations run: 2** (sweep 1: 250/257 in all 8 rounds, 7 deterministic failures; sweep 2: 257/257 in all 8 rounds).

All 7 failures were **test bugs**. The implementation required **zero changes** — every failing assertion or fixture contradicted the PRD sentence the test itself cited.

### Tests deleted
**None.** No test failed STEP 1a coverage or STEP 1b unique-derivability outright. One *assertion* was removed under STEP 1c partial-coverage handling (below).

### Fixes applied to `test_suite/`

`/home/ubuntu/.../test_suite/test_12_corner_calculations.py`
1. `TestGiftStewardshipFeeTierBoundaries::test_only_the_largest_gift_crosses_the_ratification_threshold` -> renamed `test_the_ratification_threshold_sits_between_the_two_fee_floors`; `assert required[4999999] is False` -> `is True`. The test conflated the 5000000-cent *fee* floor with the 2500000-cent *ratification* threshold. PRD line 263: "`board_ratification_required` becomes true when either `offered_amount_cents` has reached **2500000 cents**" — 4999999 >= 2500000, so the implementation was right and the assertion was arithmetically wrong.
2. Added `_clear_the_first_report(ctx)` helper and called it in `test_a_variance_of_minus_two_thousand_and_two_cannot_be_accepted` and `test_returning_the_wider_swing_clears_both_reported_figures`. Both acted on report **2** while report 1 was still `SCHEDULED`, so the PRD-required sequence gate correctly returned `ERR_REPORT_SEQUENCE_VIOLATION` during setup. PRD line 314: "Reports must be submitted in order, meaning every report of the same proposal with a lower `sequence_no` must already be in `ACCEPTED` or `WAIVED`." The helper reports bucket 1 at exactly its 175000-cent consumption (variance 0) and accepts it. Left the shared `_setup_two_reports_ready_for_review()` untouched so the sibling test that legitimately consumes report 1 still works.

`/home/ubuntu/.../test_suite/test_15_corner_validations_collaborations_and_clock.py`
3. Added `_setup_partnerless_collaboration_whose_sums_already_close()` (lead at 10000/10000 bps) for `test_a_partnerless_collaboration_cannot_activate`. The old setup left the lead at 6700 bps with no partners, so the credit-sum rung — which PRD line 326 places **above** the partner rung in ascending priority — legitimately fired `ERR_CREDIT_SHARE_SUM_INVALID` first. The class docstring's claim that "both share sums already close at 10000 bps" was false for its own fixture. The other three tests in the class still use the original 6700-bps setup, which they need.

`/home/ubuntu/.../test_suite/test_16_corner_validations_firewall.py`
4. `test_re_clearance_is_refused_while_the_disclosure_is_stale`: replaced `assert unchanged["cleared_by_user_id"] is None` with `assert unchanged["restricted_at"].startswith("2026-08-01T00:00:00")`. **STEP 1c partial coverage** — PRD covers the `ERR_DISCLOSURE_STALE` refusal and `status == RESTRICTED`, but the five-hop firewall cascade (PRD lines 229-233) never says restriction nulls `cleared_by_user_id`; it lists only `prior_editorial_requests_count`, `independence_risk_score`, `status` and `restricted_at`. The funder had genuinely been cleared by `user-ed-1` before the influence contact restricted it. The uncovered assertion was dropped and replaced with a PRD-verbatim one from the same sentence ("`restricted_at` is stamped with the logical clock").
5. `_setup_offer_in_review_with_donor_conditions()` now passes `donor_conditions=_DONOR_CONDITION` to `submit_offer_for_review`. PRD line 261: submission's "only field it takes is the optional `donor_conditions`: supplying a value replaces whatever conditions are stored, and **omitting it clears them to null** — which is the mechanism by which a donor withdraws conditions." The fixture omitted it, so the implementation correctly wiped the conditions and the two tests that depend on conditions surviving into review (`test_clearance_is_refused_while_conditions_are_still_attached`, `test_the_identical_clearance_now_succeeds_on_the_same_round_count`) had nothing left to trip on. This was `test_17_corner_validations_gift_and_delinquency.py`, and it accounted for 2 of the 7 failures.

### Fixes applied to `test_helpers/`
**None.** `submit_offer_for_review` already accepted `donor_conditions` via `**overrides`; the calling setup simply wasn't using it.

### Fixes applied to `implementation/`
**None.**

### Final per-round results
| Round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 257/257 | 257/257 | 257/257 | 257/257 | 257/257 | 257/257 | 257/257 | 257/257 |

0 failures, 0 errors, 0 skipped in every round. No flakiness observed — sweep 1's 7 failures were identical across all 8 rounds, and sweep 2 was clean across all 8.

**Orchestrator verification:** independently loaded all 8 `workspace/implementation/results.$i.json` files; each reports `passed == total == 257`. Sweep artifacts are present on disk, so the clean sweep is real and not a subagent claim. Step 8 is NOT skipped — Step 7 made 5 `test_suite/` fixes (the skip condition requires zero fixes of every kind).

## Step 8: Finalize PRD — 2026-09-04T03:52:00.000Z

## Result

`/home/ubuntu/github/CodingPRD/tasks/task_2636_nonprofit_newsroom_membership_grant_funding/workspace/PRD_FINALIZED.md` written. **507 -> 507 lines (0.0% line-count delta; 1 line revised, 0.20% of lines touched).**

Four of the five Step 7 items are pure test-fixture/assertion bugs with no PRD silence and no impl mismatch — verified against the implementation, not just against the diff narrative:

- **Item 1 (fee tier vs. ratification threshold)** — `implementation/calc.py:19-24,153-167` matches PRD line 263 exactly (`FEE_TIER_1_FLOOR_CENTS = 1000000`, `FEE_TIER_2_FLOOR_CENTS = 5000000`, `BOARD_RATIFICATION_THRESHOLD_CENTS = 2500000`, `RATIFICATION_RISK_FLOOR = 40`, inclusive `>=` on all three). No edit.
- **Item 2 (report sequence gate)** — `implementation/routes_grants.py:520-525` gates on `sequence_no` lower and status not in `("ACCEPTED", "WAIVED")`, verbatim PRD line 314, and sits below `ERR_SPEND_EXCEEDS_RELEASE` / above `ERR_REPORT_PERIOD_NOT_ELAPSED` as PRD requires. No edit.
- **Item 3 (partnerless collaboration rung order)** — `implementation/routes_collab.py:249-267` fires overlap -> credit sum -> cost sum -> no-confirmed-partner, exactly the ascending priority PRD line 326 states. No edit.
- **Item 5 (`donor_conditions` cleared on omission)** — `implementation/routes_gifts.py:116-130` sets `donor_conditions` to the request value with `default=None` unconditionally on every submission, verbatim PRD line 261. No edit.

### Changes

- **§3.4, the five-hop firewall cascade, hop 1 (line 233)** — *revise* — appended that `cleared_by_user_id` is not among the fields a restriction rewrites, so a previously cleared funder keeps that identifier while `RESTRICTED` — `implementation/derive.py:334-342` (+ `routes_firewall.py:205`).

### Pre-edit search log

**Edit 1 — hop 1 / `cleared_by_user_id`**

(a) **Subject:** the lifecycle of a `Funder`'s `cleared_by_user_id` — specifically whether any restriction path clears it.

(b) **Impl paths enumerated** (grepped `cleared_by_user_id` across all of `implementation/`, then read each hit and every restriction entry point):
- `routes_firewall.py:136` — funder creation seeds it `None`.
- `routes_firewall.py:205` — the only writer: `decision == "CLEAR"` sets it to `acting_user()`.
- `routes_firewall.py:208` -> `derive.restrict_funder(funder, "FUNDER_RESTRICTED", extra=overrides)` — the `extra` dict carries only `risk_basis` and optionally `audited_advocacy_index`; never this field.
- `derive.py:334-342` `restrict_funder` — sets only `status` and `restricted_at`, then `recompute_funder`.
- `derive.py:165-174` `recompute_funder` — writes `prior_editorial_requests_count`, `reporting_reliability_bps`, `independence_risk_score`, `lifetime_committed_cents` only.
- `derive.py:304-332` `firewall_cascade` (hops 2-5) — touches disclosures, areas, proposals, periods; no funder field.
- `routes_firewall.py:369` — influence-contact-driven restriction, no `extra`.
- `derive.py:369` — sweep/delinquency-driven restriction, no `extra`.
- Sibling `cleared_by_user_id` fields on other entities checked so the wording would not overreach: gift offers (`routes_gifts.py:75,178,183,202` — also written by `DECLINE`) and grant proposals (`routes_grants.py:92,209`).

All three restriction entry points (editorial `RESTRICT`, influence contact, delinquency sweep) leave the funder's field intact; no other entity's identically named field is implicated.

(c) **Wording adjustment:** two. (i) Scoped the sentence to the *funder*'s field and to *restriction* only, so it cannot be read as covering the gift-offer field that `DECLINE` does write. (ii) Phrased it as "is not among the fields a restriction rewrites" rather than "the fields listed above are the only ones touched" — hop 1's existing list omits `reporting_reliability_bps` and `lifetime_committed_cents`, which `derive.recompute_funder` does in fact recompute there, so an exhaustive-sounding phrasing would have manufactured a new mismatch.

### Out-of-scope observation (no edit made)

`derive.py:369` restricts a funder from the delinquency sweep with reason `FUNDER_RESTRICTED`, so cascaded disclosures get `reattestation_reason = "FUNDER_RESTRICTED"`. PRD line 234 defines that value as "when an editorial director filed the restriction directly" and `INFLUENCE_CONTACT` as the only alternative — a sweep-driven restriction is neither. This is a potential PRD/impl divergence, but it traces to no `<step_7_diff>` item, so per the hard scope I left it alone; flagging it for Step 9.

## Step 9: Complete PRD — 2026-09-04T04:43:03.414Z

Run as three sequential file-partitioned passes over `implementation/` (a single-pass scan on a 4,000-line implementation risks a silent no-op that leaves PRD_COMPLETED.md byte-identical to its source). Pass A created `PRD_COMPLETED.md` from `PRD_FINALIZED.md`; passes B and C edited it in place with the Edit tool only.

### Pass A — `core.py`, `app.py`, `guards.py`, `calc.py` — 15 edits (10 ambiguity-pins, 5 mismatch-revisions)
- §2.1 RBAC — insert — ambiguity — a present-but-empty/whitespace-only `X-User-ID` is `ERR_UNAUTHENTICATED` — core.py:326-329
- §2.2 Success envelope — revise — ambiguity — `api_request_id` is `req_` + exactly 20 chars from A-Z and 0-9 — core.py:264-268
- §2.2 Success envelope — insert — ambiguity — `api_request_timestamp` is the one timestamp read from the real wall clock, not the logical clock — core.py:274
- §2.2 Error envelope — insert — ambiguity — unrouted path / bad method render the same envelope with `ERR_INVALID_REQUEST` at the transport status (404/405); trailing slash ignored — app.py:25,40-43
- §2.3 Pagination — insert — ambiguity — out-of-range or non-integer `limit`/`offset` -> `ERR_INVALID_REQUEST`; empty value = default; bad enum/boolean filter values -> `ERR_INVALID_REQUEST`, empty ignored — core.py:566-623
- §2.3 Pagination — insert — ambiguity — `created_at` and `start_date` ties are broken by server creation order — core.py:391-392
- §2.4 Common properties — insert — mismatch — a write that changes no stored field is not a mutation (no `updated_at`/`version` bump) — core.py:368-384, 355-365
- §2.6 Basis points — revise — mismatch — per-field bps ranges (0-10000 for `lead_credit_bps`/`lead_cost_share_bps`/`award_probability_bps`, 1-10000 for partner shares); `reporting_reliability_bps` is derived and never range-checked; the rule guards only 4 operations — core.py:527-548
- §2.8 Derived fields — revise — mismatch — recomputation to an unchanged value bumps nothing — core.py:374-384
- §2.9 rung 4 — insert — ambiguity — a body FK present but not a string reports the target's not-found code — core.py:410-419
- §2.9 rung 6 — insert — ambiguity — required strings must be non-empty; booleans are not integers; missing body = empty object, non-object JSON = `ERR_INVALID_REQUEST`; natural-key uniqueness enforced here as `ERR_INVALID_REQUEST` — core.py:429-477, guards.py:12-15
- §3.4 five-hop cascade — revise — mismatch — only rows a hop actually changes bump `version` — core.py:374-384
- §3.7 cooling-off — insert — ambiguity — "within 30 days" = overlapping or a gap <= 30 days; second limb needs a restriction window on both proposals — calc.py:408-413, guards.py:95-120
- §3.7 report review — insert — ambiguity — `ACCEPTED`/`WAIVED` are the report's terminal statuses — calc.py:96
- §3.8 partner withdrawal — insert — ambiguity — `WITHDRAWN` is terminal for a partner — calc.py:100
- §3.9 acknowledgment — revise — mismatch — receipt numbers come from one server-wide sequence in arrival order, never reset per period — core.py:44-48,69-71

Verified clean in Pass A (no change needed): all 68 error-id/status mappings both ways, all 11 calculation formulas (rounding order, tie-breaking, clamping, largest-remainder ranking, month-end clamping, ceil + 45-day grace), every enum tuple and threshold constant, `round_half_up` semantics, `has_more`, clock epoch and rewind.

### Pass B — `derive.py`, `routes_fiscal.py`, `routes_membership.py`, `routes_contributions.py` — 16 edits (10 ambiguity-pins, 6 mismatch-revisions)
- §3.1 — insert — ambiguity — create + creation-time derivation is one mutation; a new period reads `version` 1, `updated_at == created_at` — routes_fiscal.py:22-27,67-68
- §3.1 — revise — ambiguity — a board override aimed at a `CLOSED` period reports `ERR_TERMINAL_STATE` — routes_fiscal.py:139
- §3.1 — insert — mismatch — cascades still write to a `REVIEW_LOCKED`/`CLOSED` period; the close's freeze binds only the client-driven writes — derive.py:280-297, routes_fiscal.py:233
- §3.3 — insert — ambiguity — the sweep runs two ordered member passes then the report pass, so a member can travel `ACTIVE->GRACE->LAPSED` in one sweep and count in both counters — routes_fiscal.py:197-233
- §3.3 — revise — ambiguity — the `cultivation_locked` reinstatement refusal is `ERR_INVALID_STATE`, after the tier-published gate — routes_membership.py:238-239
- §3.3 — revise — ambiguity — same-tier and cultivation-locked tier-change refusals are both `ERR_INVALID_STATE`, below the tier-published and member-status gates — routes_membership.py:270-273
- §3.3 — revise — ambiguity — tier change leaves `cycle_start_date` alone; `grace_expires_at` is re-derived for a `GRACE` member from the new tier's `grace_period_days`, stays null for an `ACTIVE` one — derive.py:202-211
- §3.4 hop 2 — revise — mismatch (the divergence Step 8 flagged) — `reattestation_reason` is `INFLUENCE_CONTACT` only when a logged influence contact drove the restriction; `FUNDER_RESTRICTED` on every other path, covering both a direct editorial filing and the sweep's delinquency cascade — derive.py:369, routes_firewall.py:208,369
- §3.4 hop 5 — insert — mismatch — the reserve debit and the sustainability re-derivation are one write, so `version` bumps by exactly 1 — derive.py:16-37,292-294
- §3.7 — revise — ambiguity — delinquency restriction fires only while the funder is `PROSPECT`/`CLEARED`; an already-`RESTRICTED` funder runs no second cascade and adds nothing to `funders_restricted` — derive.py:367-369
- §3.9 — revise — mismatch — `MAJOR_GIFT` may be recorded directly; any stream carrying a `funder_id` requires a non-`RESTRICTED` funder, ranked ahead of the source rules; stream mismatch outranks the tier minimum — routes_contributions.py:63-100
- §3.9 — revise — ambiguity — an out-of-range `received_date` is `ERR_INVALID_REQUEST`, reported ahead of period lockedness — routes_contributions.py:69-73
- §3.9 — revise — mismatch — the period must be `OPEN` for either settlement outcome, not only `SETTLED` — routes_contributions.py:177
- §3.9 — revise — ambiguity — the refund's linked funder is the member's `linked_funder_id` whenever the row names a `member_id`, else the row's own `funder_id`; a `SYNDICATION` refund also recomputes the collaboration's `syndication_revenue_cents` — routes_contributions.py:233-244
- §3.9 — revise — ambiguity — receipting a `FAILED` row and publishing a non-`SETTLED` row are both `ERR_INVALID_STATE`; a designated `MAJOR_GIFT` needs an `ACTIVE` disclosure — routes_contributions.py:262-280
- §4 `POST /members` — revise — mismatch — "the first ACTIVATE sets the renewal cycle" (no such action exists) -> the settlement of the first `MEMBERSHIP` contribution sets it — routes_contributions.py:188-198

### Pass C — `routes_firewall.py`, `routes_grants.py`, `routes_collab.py`, `routes_gifts.py` — 35 findings over 36 edits (23 ambiguity-pins, 12 mismatch-revisions)
Mismatch-revisions:
- §2.9 rung 4 — a required body FK that is absent/null is `ERR_INVALID_REQUEST` at the point the field is reached, before later-declared FKs resolve — routes_firewall.py:220-226, routes_gifts.py:46-52, routes_collab.py:46-53
- §2.7 — a filing retires the prior disclosure of a pair only when it names it in `supersedes_disclosure_id`; otherwise a pair holds two `ACTIVE` disclosures — routes_firewall.py:255
- §3.1 — the period-locked list is eight operations, adding grant `SUBMIT` — routes_grants.py:174
- §3.4 — `total_committed_cents` sums each disclosed funder's whole `lifetime_committed_cents`, not what it committed to the beat — routes_firewall.py:96
- §3.6 — accept gate order is period -> dual control -> funder `CLEARED` -> publication gate -> board ratification — routes_gifts.py:217-227
- §3.7 — the three restriction-scope fields are stored verbatim, not forced null, on an `UNRESTRICTED` draft — routes_grants.py:58-78
- §3.7 — `SUBMIT`'s publication gate outranks cooling-off; its period check sits at the bottom of the endpoint's ladder — routes_grants.py:168-174
- §3.7 — release's period check is evaluated first, above terminal/state and all four money gates — routes_grants.py:352-355
- §3.7 — report submit's `ERR_SPEND_EXCEEDS_RELEASE` outranks every state guard on the endpoint — routes_grants.py:505-517
- §3.7 — `RETURN` also recomputes `compliance_flag` and can lift `DELINQUENT`; submission alone never does (old prose asserted the opposite) — routes_grants.py:570
- §3.8 — `ACTIVATE`'s publication gate outranks all four arithmetic gates; the period check outranks terminal/state for all three actions — routes_collab.py:232-267
- §3.8 — `allocated_cost_cents == total_cost_cents` holds only where shares close at 10000 bps (guaranteed from `ACTIVE` onward), not always — routes_collab.py:268-296

Ambiguity-pins: `disclosed_funder_ids` ordering and ignored pagination (routes_firewall.py:90); fresh funder reads `version` 1 (140-141); `lifetime_committed_cents` refreshes only on writes to the funder row, so suspend/reinstate leave it stale (all recompute_funder callsites); `basis` mandatory and `AUDITED` requires `audited_advocacy_index` (179-190); a void needs no dual control and leaves attestation fields standing (305-321); a contact against an already-`RESTRICTED` funder records `triggered_restriction` false and fires no cascade (366-369); a `PROPOSED` offer's netting fields seed 0/0/false (routes_gifts.py:70-72); `REQUEST_CONDITIONS` without `review_note` clears `donor_conditions` (142,162); `received_date` shape-checked only (213); cascade contribution's `source_label` is the funder's `legal_name` with member/collaboration/receipt/refund fields null (232-247); `ERR_FUNDER_NOT_INSTITUTIONAL` ranks below bps/date checks (routes_grants.py:64-68); `SUBMIT_FOR_REVIEW`'s missing window is `ERR_INVALID_REQUEST` below terminal/transition guards (153-163); a `DECLINED` outcome checks only period + `SUBMITTED` (299-306); **[Pass B candidate, verified]** the clawback leaves every report's `consumed_release_cents` standing and only reinstatement zeroes them (derive.py:280-300 vs routes_grants.py:405); closure blockers are `ERR_INVALID_STATE` while a missing `closure_justification` is `ERR_INVALID_REQUEST` (437,442); `spend_reported_cents` required, minimum 0 (505); a wrong proposal status on report submit is `ERR_INVALID_STATE` below the report's own state guards (519); `window_start`/`window_end` are instants, date-only accepted as midnight UTC (routes_collab.py:55-56); period containment compares calendar-date parts after the date-pair check (67); partner add to `SETTLED`/`DISSOLVED` is `ERR_TERMINAL_STATE`, and a partner added to an `ACTIVE` collaboration returns already allocated at `version` 1 (132-155); `SETTLE`'s allocation mismatch is `ERR_INVALID_STATE` after the window-closed gate (275-277); `DISSOLVE` zeroes `cost_owed_cents` but leaves `remainder_rank` (288-292); withdrawal against a `SETTLED` collaboration is `ERR_INVALID_STATE` and the endpoint has no period check (185-188).

Pass C confirmed its edited lines were disjoint from passes A and B, so no earlier wording was undone.

### Totals and orchestrator verification
- 66 edits across the three passes: 43 ambiguity-pins, 23 mismatch-revisions.
- `PRD_FINALIZED.md` 507 lines -> `PRD_COMPLETED.md` 508 lines (+1 line, 118,632 -> 126,887 bytes, +8,255 chars); nearly every edit is in-paragraph.
- Independently verified by the orchestrator: `PRD_COMPLETED.md` is 508 lines, is NOT byte-identical to `PRD_FINALIZED.md` (200-line diff, so the scan genuinely ran), ends at the complete final row of the §5 catalogue, and still carries 67 §4 endpoint rows and 68 distinct error ids. `PRD.md` and `PRD_FINALIZED.md` are untouched at 507 lines each.
- Step 9 touched documentation only; `implementation/` and the test artifacts are unchanged since the clean Step 7 sweep, whose 8 `results.$i.json` files (all 257/257) remain on disk.

Pipeline complete.
