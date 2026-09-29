# Worklog — task_2649_single_family_rental_portfolio_operations

## Step 1: Create task directory — 2026-09-04T00:58:40.942Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2649_single_family_rental_portfolio_operations` and `.../workspace` using the pre-assigned path from the invocation (no index auto-allocation, per orchestrator instructions — other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-04T02:59:30.000Z

All three artifacts are complete and lint-clean.

**Output** — `/home/ubuntu/github/CodingPRD/tasks/task_2649_single_family_rental_portfolio_operations/`
- `SCAFFOLD.yaml` (3,942 lines) — §1.0–§1.7 only; contains neither `scaffold_difficulty_design` nor `scaffold_corner_design`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2,230 lines) — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (4,804 lines) — single top-level key `scaffold_corner_design`

**Lint verdict (verbatim)**
```
Coverage
  §1.5 endpoints declared:    68
  §1.1 entities declared:     13
  §1.8 instances scanned:     20
  §1.9 instances scanned:     62
  Calls scanned (§1.8+§1.9):  963

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Coverage / counts**
- §1.0: complexity_layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; entity_topology graph; role_model segregation_of_duties; consistency_model immediate; logical clock default 2026-08-01Z
- §1.1: **13 entities** (Market, ScopeTemplate, Home, UnderwritingCase, Vendor, VendorCertification, RenovationProject, WorkOrder, Prospect, ShowingSlot, RentalApplication, Lease, ComplianceObligation)
- §1.2: 9 state machines incl. Home's two independent dimensions (asset_status / occupancy_status); §1.2.1: 2 OCC rules (`expected_home_version`, `expected_prospect_version`, both 412)
- §1.3: **9 calculations** (scope_benchmark_total, yield_on_cost with underwritten/realized variants, prospect_fraud_risk_score with pre/post-verification variants, home_leasing_posture, screening_decision, turn_holdback, tax_appeal_savings, vendor_dispatch_selection, work_order_crew_days)
- §1.4: **69 ordered validations** (V010→V618, two deliberately inverted priority pairs); §1.6: **68 errors**, every one triggered by at least one instance (verified programmatically, zero uncovered); §1.5: **68 endpoints**; §1.7: **12 roles**
- §1.8: **20 difficulty instances** across all 9 rule_ids
- §1.9: **79 corner instances** across all 9 sections — entities 15, state_machines 21, calculations 11, validations 14, endpoints 6, errors 2, rbac 4, cross_cutting_complexity_layers 5, consistency_model 1. 62 carry full `test_recipe`s; 17 are `excluded_because` stubs, each citing an existing §1.8 instance by exact name and carrying no test_recipe. No duplicate instance names across the two design files.

**Two SCAFFOLD.yaml corrections made while writing §1.9:** ERR_WORK_ORDER_NOT_ASSIGNED was unreachable behind the p300 state guard, so its rule moved to a new priority-250 "structural integrity" band (V412 deleted, V250 added, `raised_by` updated); and `GET /work-orders/{workOrderId}/vendor-ranking` gained a `note:` pinning the ordering/alignment of `eligible_vendor_ids`/`bid_cents` and the `exclusion_reasons` vocabulary (the four vendor-eligibility error ids) so the corner instance and §1.5 agree.

## Step 3: Copy shared files — 2026-09-04T03:00:36.505Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T03:19:01.961Z

PRD generation for task 2649 is complete.

**Output:** `workspace/PRD.md` — 586 lines, 120,390 bytes. Written in 8 chunks (initial `Write`, then quoted heredoc appends plus two programmatic table appends), with `wc -l`/`tail` after every append. No truncation; the file ends at a real boundary (last row of the §5 error table).

**Sections emitted**
- Title + `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` with 2.1 RBAC (12 roles, entity-backed `Vendor`/`Prospect` identity), 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Identity/common fields/logical clock, 2.5 Money & round-half-up, 2.6 OCC (`expected_home_version`, `expected_prospect_version`), 2.7 Validation Precedence (full 69-rank ladder + the three deliberate ordering conflicts), 2.8 Two-dimensional Home & leasing-posture gate, 2.9 Cascade discipline & the three conserved ledgers, 2.10 Market policy ranges
- `## 3. Business Logic & Workflows` §3.1 market/scope catalogue/home register, §3.2 underwriting & committee cycle (dual-variant yield, per-line vs index-the-sum contrast 1479843 vs 1479844, 559 vs 531 bps), §3.3 projects/budget ledger/work orders, §3.4 vendor network & dispatch ranking, §3.5 execution/void/turn-holdback (all three worked settlements incl. the binding cap), §3.6 prospect + dual-variant fraud scoring (all five worked scores incl. the exact-6000 boundary and the liveness override), §3.7 showing calendar, §3.8 screening/deposits/lease, §3.9 compliance/tax appeal/disposition
- `## 4. API Endpoints` (68-row table: Method, Path, Description, Authorized Roles)
- `## 5. Error Codes` (68-row table: Error Code, HTTP Status, Description)

**Verification (all mechanical, run against SCAFFOLD.yaml)**
- Contract 1 — Field-Name Coverage: **PASS**, 202/202 required identifiers present verbatim in backticks (167 entity fields, 140 request-body/computed-read identifiers, 29 query params, 13 path params; the 13 path params were added to the §2.7 existence ranks to make them explicit).
- Contract 2 — Rule Coverage: **PASS**. 69/69 validations present as ranked ladder items (priority set matches the scaffold exactly, no extras, no omissions); 68/68 distinct error ids present; **50/50 state transitions** stated with explicit `FROM` → `TO` notation across all 9 state machines; both concurrency rules; all 9 calculations; 89/89 enum values, state names and role names.
- Contract 3 — §3 Path Purity: **PASS**. 1,094 backticked tokens in §3, zero starting with `/`, zero bare HTTP methods, zero method+path combos, and zero unbackticked `METHOD /path` strings in prose.
- §2.2 byte-identical to `section-2.2-response-structure.md`.
- No pseudocode operators and no fuzzy words anywhere outside the §2.2 JSON envelope.

**Two judgement calls worth recording**
1. The scaffold's error message for `ERR_INVALID_ROLE` names the header `X-Role`; the skill mandates `X-User-Role`. The PRD uses `X-User-Role` throughout, including in that error's description.
2. Scaffold gap: `VendorCertification` has no `status` field in §1.1, yet V156, the revoke endpoint and the `status?` list filter all assume one. The PRD states that a certification carries `status` of `ACTIVE` or `REVOKED`, defaulting to `ACTIVE`, and that revocation supplies `reason` — the only place the PRD fills a hole rather than projecting an explicit seed row.

Both withheld design files were never opened, grepped or referenced, and no sibling task directory was read.

**Orchestrator truncation check (independent):** `tail` shows the file ending on the final alphabetically-sorted error row (`ERR_YIELD_BELOW_FLOOR`); 68/68 scaffold error ids and 68/68 scaffold endpoint paths verified present by script; `grep -ic expert` = 0, so the Step 2 difficulty instruction did not leak into PRD.md.

## Step 5: Generate unit tests — 2026-09-04T04:58:00.324Z

Stage 2 is complete. All 82 tests are collected by pytest, every file compiles, and pyflakes is clean apart from two deliberate, pre-existing exceptions in `test_helpers/`.

### Files written this session (`test_suite/`)

| file | tests | queue B instances |
|---|---|---|
| `test_b_endpoints_actions.py` | 3 (298 L) | vendor PATCH versioning; the two-step INDIVIDUAL sale (refused while `RESERVED`, accepted after the void, `realized_gain_cents` 3950000, second `CLOSE_SALE` → `ERR_INVALID_STATE`); obligation→work-order link queryable by filter |
| `test_b_rbac_authority.py` | 2 (206 L) | role denial (403 beats 404 because rank 40 precedes rank 54); segregation of duties firing twice on one scenario, keyed on `X-User-ID` |
| `test_b_rbac_ownership.py` | 2 (233 L) | `ERR_NOT_ASSIGNED_VENDOR` for the peer vendor on accept and complete, with only the assignee's 9 crew-days released; `ERR_NOT_SLOT_OWNER` per booking, plus the agent's unrestricted cancel |
| `test_b_error_envelope.py` | 2 (156 L) | header ladder (`ERR_INVALID_ROLE` before `ERR_UNAUTHENTICATED`, clock setter exempt); one envelope across 400/403/404/409/422 with no rows written |
| `test_b_concurrency.py` | 2 (179 L) | `ERR_STALE_HOME_VERSION` then two accepted creates on the same version (supersede); `ERR_STALE_PROSPECT_VERSION` on a replayed pre-verification version, score 1093 both times |
| `test_b_consistency_model.py` | 1 (86 L) | derived fields present in the mutation body itself (tax 350000→310000, full deposit group, `RESERVED` on the next read) |

### Final inventory

- `test_helpers/` — 9 files, 2142 lines.
- `test_suite/` — `conftest.py` + 30 test files, 6585 lines, **82 tests**.
- Queue A: **20/20** instances across 9 `test_a_*.py` files.
- Queue B: **62/62 live instances** across 21 `test_b_*.py` files (the yaml's other 17 stubs carry `excluded_because` and were never live). Per-section: entities 15, state_machines 14, validations 12, calculations 6, endpoints 6, rbac 4, errors 2, cross_cutting_complexity_layers 2, consistency_model 1.
- **Zero instances skipped.** Every test carries exactly one `Design:` line; a script re-validated all 82 tags against `name:`/`rule_id:` in both yamls — no unknown instances, no duplicates, no dual tags.
- `workspace/` contains only `INSTRUCTION.md`, `PRD.md` and `implementation/` (never read or written). No `__pycache__` left behind.

### PRD / design-index gaps (for the worklog)

Six instances were translated minus one assertion each, with an inline comment quoting the contradiction; none was weakened otherwise:

1. `hold_sell_score_bps` — §3.1 says a new home starts at `0`, §3.2 says it "is null while the home has no `APPROVED` case at all". Three corner instances assert null; that one field is not asserted.
2. `Prospect.booked_showing_count` does not exist (PRD defines it on `Home` only) — substituted the Home assertion in `test_a_priority.py`.
3. `missing_required_fields_returns_invalid_request` expects 400 for a `POST /homes` omitting `asking_rent_cents`, but §3.1 makes that field optional (defaults to the market's `rent_index_cents`) — that trigger call was dropped.
4. `posture_clause_order_reads_back_as_five_then_four_then_three` asserts a still-open MAJOR obligation appears in `blocking_obligation_ids` while clause 3 decides; §2.8 only says the list holds obligations "that contributed to the decision" — that one assertion omitted.
5. Two instances (`prospect_may_only_cancel_the_slot_it_booked`, `error_envelope_is_uniform_...`) publish a showing window with `access_mode: SELF_SHOWING`, which is not in §3.7's exhaustive enum (`SMART_LOCK`, `LOCKBOX`, `AGENT_ESCORT`). Both use `SMART_LOCK`; the access mode is incidental to each refusal under test.
6. `identity_reverification_...` writes `fraud_score_variant == post_verification`; §3.6 stamps `POST_VERIFICATION`. The test asserts the PRD's casing.

**Orchestrator layout check:** `test_helpers/` and `test_suite/` are both at the task root; `workspace/` holds only INSTRUCTION.md, PRD.md, implementation/ — no stray test dirs to move before Step 7.

## Step 6: Generate implementation — 2026-09-04T04:58:00.324Z

Implementation complete and smoke-tested.

### Modules (all under `workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `calc.py` | 429 | C1–C9 pure calculations |
| `routes_leasing.py` | 260 | applications, screening, leases |
| `routes_workorder.py` | 253 | work orders, dispatch, complete, void |
| `routes_prospect.py` | 249 | prospects, identity, showing calendar |
| `cascades.py` | 247 | multi-hop side-effect chains |
| `validation.py` | 226 | rank 10/12 payload validation + rank 20/30/40 auth |
| `routes_compliance.py` | 207 | obligations, tax appeals |
| `routes_home.py` / `routes_underwriting.py` | 197 / 197 | homes + posture + disposition; cases |
| `routes_vendor.py` | 166 | vendors, certifications |
| `store.py` / `routes_core.py` | 143 / 143 | in-memory dicts + logical clock; clock/markets/templates |
| `routes_project.py` | 135 | projects, budget, lock-scope, benchmark summary |
| `app.py` 95, `errors.py` 92, `envelope.py` 75, `views.py` 43, `start.sh` 10, `requirements.txt` 1 | | wiring, 70-entry error catalog, envelope/pagination, serializers |

Total 3168 lines, 17 Python modules, all byte-compiling.

### Coverage
- **68/68 PRD endpoints** registered (69 Flask rules = 68 + Flask's `/static`).
- **Calculations C1–C9**: per-line benchmark vs index-the-sum, dual-variant yield-on-cost, dual-variant fraud score, 6-clause leasing posture, screening/deposit stack, turn-holdback tiering with gross-based cap, tax-appeal savings, vendor eligibility/ranking/per-date capacity, crew days. All integer half-up (`(2n+d)//(2d)`), no floats.
- **Validation ladder**: numeric rank order enforced everywhere — rank 10 payload before 20/30/40 auth, rank 12 interval checks before role checks, rank 250 (vendor-channel-only) before rank 300, rank 302 before 420, rank 502 before 602.
- **Storage**: pure in-memory dicts, nothing seeded, no disk artifacts.

### Smoke results (port 39823, then 39824; each server killed by captured pid — no broad pkill)
Four scenario scripts, **~190 assertions, 0 implementation failures**:
- Full happy path: market → template → home → case (submit/approve with distinct users) → project → work order → dispatch/accept/complete → make-ready cascade → prospect → identity verification → slot → book → application → screen → lease → deposit → execute → tax-appeal cascade.
- PRD worked examples reproduced exactly: underwritten yield 656 bps, realized group (105000/24405000/1601184/656), fraud 4850 → 1093, 7860 → 6107, 4313 (liveness override), 360; screening 3839 bps / 15000 multiplier / 352500 deposit stack; holdback example 1 (32 days → 152000, net 1368000) and example 2 (34 days → cap binds at 228000, net 1292000); tax appeal 40000/12000/28000 with home reassessed to 24800000 and tax 310000.
- ~45 error paths confirmed with correct id + status, including `ERR_INVALID_REQUEST` 400 ahead of role checks, both stale-version 412s, `ERR_SEGREGATION_OF_DUTIES`, `ERR_YIELD_BELOW_FLOOR`, `ERR_REVISION_LIMIT_EXCEEDED`, `ERR_VENDOR_CAPACITY_EXCEEDED`/`INACTIVE`/`NOT_CERTIFIED`, `ERR_BUDGET_BELOW_COMMITTED`, `ERR_COMPLETION_DATE_INVALID`, terminal-state guards on `PASSED`/`DISPOSED`.
- Invariants held after every mutation: project money conservation, vendor `committed_crew_days` = Σ over {DISPATCHED, ACCEPTED}, `booked_showing_count`, and posture-driven `AVAILABLE ⇄ BLOCKED_BY_POSTURE` transitions that never touch `BOOKED` slots.
- **Per-test-server readiness**: three consecutive `PORT=… bash start.sh` boots each came up in ~2.5 s with `markets_total=0`, `homes_total=0`, clock back at `2026-08-01T00:00:00.000Z`.

Three initial "failures" were the smoke script's wrong expectations, each resolved against the PRD in the implementation's favour: `rent_ready_on` is the logical-clock date (PRD §3.5 hop 1); rank 250 is vendor-channel-only so accepting an in-house `IN_PROGRESS` row correctly yields `ERR_INVALID_STATE`; `CLOSE_SALE` yields `DISPOSED`, and new slots are always created `AVAILABLE` even on a frozen home (PRD §3.7).

## Step 7: Iterate tests + fixes — 2026-09-04 (diagnostic loop)

Two parallel 8-round sweeps (`--isolation per-test-server`, 82 tests/round).

**Iteration 1** — 75/82 in all 8 rounds; the same 7 failures every round (fully deterministic, no flakiness).

| failing test | diagnosis | layer fixed |
|---|---|---|
| `test_home_listing_filters_before_it_counts_and_pages`, `test_off_range_off_enum_and_negative_money_are_all_rank_ten_failures`, `test_five_refusals_five_status_codes_one_envelope_and_no_rows_written` | `TypeError: market_payload() got multiple values for keyword argument 'millage_bps'` — `dallas_market_payload`/`dallas_market_payload_strict` forwarded `**overrides` alongside their own pinned kwargs, so any test re-overriding a pinned field (or simply calling `dallas_market_payload_strict()`) crashed at collection of the payload | `test_helpers/factories.py` |
| `test_the_clock_is_re_settable_...`, `test_a_bad_role_answers_before_a_missing_principal_...` | `GET /_clock` returned `2026-08-01T00:00:00.000Z`; PRD §2.4 and the §4 endpoint table both render the clock value verbatim as `2026-08-01T00:00:00Z`, and `current_utc` is not one of the fields §2.2 declares to carry three fractional digits | `workspace/implementation/store.py`, `routes_core.py` |
| `test_the_fraud_score_is_divided_and_rounded_exactly_once_at_the_end` | asserted HTTP 201 on `POST /prospects/{id}/identity-verifications`; that attempt modifies the existing prospect row, so PRD §4 mandates 200 — the suite's four other verify-identity tests already assert 200 | `test_suite/test_b_calculations.py` |
| `test_one_rejection_walks_the_home_to_passed_and_freezes_the_calendar` | read `GET /homes/{homeId}/leasing-posture` as `AcquisitionAnalyst`, a role PRD §4 does not authorize for that endpoint | `test_suite/test_b_state_cascades.py` |

No test was deleted, skipped or weakened; no PRD-required implementation check was removed.

**Iteration 2** — 82/82 in all eight rounds (results.1..8.json), 155 s per round.

## Step 7: Run tests and iterate — 2026-09-04T05:24:05.474Z

Clean 8-round sweep achieved.

**Iterations run:** 2 (each a full 8-round parallel sweep under `setsid nohup`, `per-test-server` isolation, 82 tests/round).

**Iteration 1 result:** 75/82 in every round — 7 failures, identical in all 8 rounds (fully deterministic, zero flakiness, zero load-induced noise).

**Tests deleted:** none. Every failure traced either to a test-layer bug or to a verbatim-PRD violation in the implementation; no test asserted a scaffold-only or PRD-silent rule.

**Fixes applied to `test_helpers/`:**
- `test_helpers/factories.py` — `dallas_market_payload` and `dallas_market_payload_strict` forwarded `**overrides` next to their own pinned kwargs, so `market_payload() got multiple values for keyword argument 'millage_bps'`; both now build their defaults and then layer overrides via `_apply`. This was the classic shared-upstream-fixture bug that killed 3 tests. The same latent pattern in `scope_template_general`, `home_payload_no_hoa`, `home_payload_second`, `home_payload_dallas` and `turn_project_payload` was hardened the same way.

**Fixes applied to `test_suite/`:**
- `test_b_calculations.py::test_the_fraud_score_is_divided_and_rounded_exactly_once_at_the_end` — asserted 201 on `POST /prospects/{id}/identity-verifications`; that attempt modifies the existing prospect row, so PRD §4 mandates 200 ("Endpoints that read, list or modify an existing resource return HTTP 200"). The suite's four other verify-identity tests already assert 200. The scoring assertions (`fraud_risk_score_bps=5401`, `!= 5400`) were untouched and the implementation already produced them.
- `test_b_state_cascades.py::test_one_rejection_walks_the_home_to_passed_and_freezes_the_calendar` — read `GET /homes/{homeId}/leasing-posture` as `AcquisitionAnalyst`, a role PRD §4 line 456 does not authorize for that endpoint; switched to `LeasingAgent`. The `ERR_UNAUTHORIZED` the implementation raised was PRD-correct, so the fixture identity was fixed rather than the check.

**Fixes applied to `implementation/`:**
- `store.py` (`clock_set`, new `clock_text`) and `routes_core.py` (`set_clock`, `read_clock`) — the clock read re-rendered `current_utc` with three fractional digits (`2026-08-01T00:00:00.000Z`). PRD §2.4 and the §4 endpoint table both print the clock value verbatim as `2026-08-01T00:00:00Z`, and §2.2 lists `starts_at`/`ends_at` — not `current_utc` — as the instant fields carrying three fractional digits. The clock now preserves the supplied instant text and boots at the literal PRD string.

**Final sweep evidence** (`workspace/implementation/results.$i.json`): rounds 1–8 all 82/82, ~155 s each.

No skips, no xfails, no error_id→HTTP-status downgrades, no seeded storage, and no endpoint/field/side-effect added to the implementation.

**Orchestrator independent verification:** all 8 `results.$i.json` exist (mtime 2026-09-04 05:16, within seconds of each other) and each reports `passed=82 total=82 failed=0` — re-read directly from disk by the orchestrator, not taken from the subagent's claim.

## Step 8: Finalize PRD — 2026-09-04T05:27:23.257Z

Done. `PRD_FINALIZED.md` written with two surgical edits.

**Line counts:** PRD.md 586 lines / 120390 bytes → PRD_FINALIZED.md 586 lines / 120909 bytes (0% line delta, +0.43% bytes).

**Changes**
- §2.4 (Dates, Instants and the Logical Clock) — revise — pinned that a clock read (and the setter's own HTTP 200 response) returns `current_utc` as the instant text exactly as the last accepted set supplied it, un-re-rendered, and the literal `2026-08-01T00:00:00Z` before any set — `implementation/store.py:40-60`, `implementation/routes_core.py:24-37`.
- §3.6 (Prospect Registration, Identity Verification…) — insert — pinned that an identity-verification attempt persists no separate resource, modifies the prospect in place, and returns HTTP 200 with the updated prospect — `implementation/routes_prospect.py:94-118`.

**Not patched (PRD already determined; no silence/mismatch)**
- `test_helpers/factories.py` `**overrides` collisions — pure fixture bug, no behavioral content.
- `leasing-posture` role fix — impl's `POSTURE_READ` (`routes_home.py:16-17`) is byte-for-byte the PRD §4 list; the test's role was wrong, not the PRD.
- Fraud-score single-final-rounding assertions (`5401`) — already pinned verbatim in §3.6; only the status code in that test was wrong, covered by the §3.6 edit.

**Per-edit pre-edit search log**

Edit 1 — subject: rendering/format of the logical clock's `current_utc` in both clock endpoints.
(b) Enumerated and read: `store.py` (`CLOCK_BOOT`, `CLOCK_BOOT_TEXT`, `clock_set`, `clock_text`, `clock_now`, `clock_date`, `fmt_instant`, `iso_now`), `routes_core.py:24-37` (`set_clock`, `read_clock`), `validation.py:69-78` (`parse_instant_value` — accepts `Z`/`z`/offset forms and whitespace, so the stored raw text can be any of them), `envelope.py` (`ok`/`created`/`_meta`), plus every clock consumer via grep: `calc.py:212,348,391`, `cascades.py:208`, `routes_prospect.py:148` — all read the parsed datetime/date, never the text, so text-preservation affects nothing but the two clock responses.
(c) Adjustment: dropped a planned "unlike the §2.2 instant fields, not normalised to three fractional digits" contrast. `routes_prospect.py:167-168` stores `starts_at`/`ends_at` as the client's raw strings too, so a sentence asserting those fields *are* re-rendered would have created a new mismatch. Wording narrowed to "not re-rendered" about `current_utc` alone. Also used "most recent accepted set" so a rejected set leaving the old text is covered.

Edit 2 — subject: HTTP status and response payload of `POST /prospects/{prospectId}/identity-verifications`.
(b) Enumerated and read: `routes_prospect.py:94-118` (`verify_identity`, returns `ok(views.public(prospect))`), `store.py:16-30` (`COLLECTIONS` — no verification-attempt collection exists anywhere), `views.py:9-17`, `envelope.py:20-26` (`ok`=200, `created`=201), the `cascades.release_booked_slots_for_prospect` callsite, and a repo-wide grep for `created(` across all nine route modules — all eleven 201 sites are genuine row inserts, so the §4 create/modify dichotomy stays true globally.
(c) Adjustment: scoped the sentence to this endpoint and phrased it as "one of the modifying endpoints of §4" rather than adding any new global rule about POST-shaped action endpoints (`/dispatch`, `/screen`, `/book`, `/cancel`, `/void`, `/status`, `/revoke` all already return 200 under the existing §4 sentence).

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly two changed lines (95 and 351), both in-paragraph revisions with no new sections; file still ends at the final error-table row.

## Step 9: Complete PRD — 2026-09-04T05:54:47.240Z

Run as **three sequential file-partitioned passes** over the 17-module implementation (orchestrator decision: a single monolithic Step 9 pass on an impl this large routinely returns a byte-identical PRD_COMPLETED.md — partitioning forces each pass to actually walk its files). Pass 1 created PRD_COMPLETED.md from PRD_FINALIZED.md; passes 2 and 3 edited it in place with explicit "do not re-copy" instructions.

### Pass 1 — app.py, store.py, envelope.py, errors.py, views.py, validation.py, routes_core.py, routes_home.py, routes_underwriting.py, routes_project.py
586 → 588 lines, 120,909 → 125,035 bytes. **16 ambiguity-pins, 3 mismatch-revisions** (19 edits).
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase letters/digits — store.py:92
- §2.3 — insert — ambiguity — `offset` unbounded; empty value → default; non-base-10 integer → `ERR_INVALID_REQUEST`; pagination/filter params examined only after §2.1 role checks — envelope.py:48-66
- §2.3 — insert — ambiguity — `created_at` ties broken by server creation sequence; boolean filters accept `true|false|1|0` else 400; string/enum filters exact-equality, non-matching value → empty page — store.py:124, envelope.py:72, views.py:20-43
- §2.4 — insert — ambiguity — `created_at`/`updated_at` come from real server time, never the logical clock — store.py:80-89
- §2.4 — insert — ambiguity — instant inputs accept any ISO 8601 (`Z` or offset, with/without fraction) normalised to UTC; date inputs strict `YYYY-MM-DD` only — validation.py:60-78
- §2.7 rank 10 — insert — ambiguity — JSON `null` treated as absent; undeclared fields ignored; absent body accepted when all fields optional — validation.py:157-196
- §2.9 — insert — ambiguity — a row reached by several hops in one request is incremented by exactly 1 — store.py:127-153
- §2.10 — insert — ambiguity — `restricted_breeds` stored verbatim, no casing normalisation, exact-equality matching — routes_core.py:59
- §3.1 — insert — ambiguity — `bathrooms` may not be negative — validation.py:125-129
- §3.1 — insert — ambiguity — an accepted PATCH always bumps `version` by exactly 1, even with an empty payload — routes_home.py:126
- §3.2 — **revise — mismatch** — `hold_sell_score_bps` is 0 (not null) with `disposition_flagged` false while the home has no `APPROVED` case — routes_home.py:83, cascades.py:83-91
- §3.2 — insert — ambiguity — empty planned scope on submit → `ERR_PROJECT_SCOPE_EMPTY` — routes_underwriting.py:110
- §3.2 — insert — ambiguity — `→ACQUIRED`/`→PASSED` hops conditional on home still `PIPELINE`; a revision request leaves `decided_by_user_id` empty and touches neither posture nor calendar — routes_underwriting.py:154-174
- §3.3 — **revise — mismatch** — turn metrics/holdback figures are `null` until rent-ready — routes_project.py:44-49
- §3.3 — insert — ambiguity — budget revision accepted from any project status incl. `RENT_READY` — routes_project.py:74-85
- §3.9 — insert — ambiguity — `APPROVE_SALE`: `FROZEN` posture refused with `ERR_DISPOSITION_NOT_ELIGIBLE` ahead of the occupancy test; omitted `disposition_mode` stored `NONE`; omitted `bpo_value_cents` leaves stored figure; `lot_code` stored verbatim in any mode — routes_home.py:164-181
- §3.9 — insert — ambiguity — `CLOSE_SALE`: basis 0 with no `APPROVED` case; no posture/occupancy gate; other disposition fields left as `APPROVE_SALE` left them — routes_home.py:184-196
- §4 — insert — ambiguity — unknown path / unsupported method return the error envelope with `ERR_INVALID_REQUEST` under 404 / 405 — app.py:66-72
- §5 — insert — **mismatch** — added missing `ERR_DUPLICATE_PROSPECT_EMAIL` (409) and `ERR_COMPLETION_DATE_INVALID` (422) rows — errors.py:30,73

### Pass 2 — calc.py, cascades.py, routes_vendor.py, routes_workorder.py
588 → 591 lines, 125,035 → 132,253 bytes. **13 ambiguity-pins, 5 mismatch-revisions** (18 edits).
- §2.7 — insert — ambiguity — new item 70, rank 620 `ERR_COMPLETION_DATE_INVALID`, last check, below rank 300/352 — routes_workorder.py:205
- §2.5 — insert — ambiguity — half-up is away from zero (−2.5 → −3); names the two reachable negative divisions; exact integer arithmetic — calc.py:16
- §2.8 — insert — ambiguity — `blocking_obligation_ids` filled only by clauses 3/4 at the deciding severity, empty for 1/2/5/6, ordered by obligation creation; `binder_expired` independent of winning clause — calc.py:215
- §3.2 — insert — ambiguity — with several `APPROVED` cases the earliest-created one is read/written — cascades.py:35
- §3.2 — revise — mismatch — a **void** driving a project rent-ready is also a realized-variant trigger (PRD said "exactly three moments") — routes_workorder.py:252
- §3.3 — insert — ambiguity — no cross-check between `project_id` and `home_id` — routes_workorder.py:49
- §3.3 — insert — mismatch — the First/Second/Third narrative is not precedence; scope-lock (304) runs ahead of variance (604) and budget (606) — routes_workorder.py:54
- §3.4 — insert — ambiguity — empty vendor PATCH still bumps `version`; `suspension_reason` cleared to `""` only on an omitting move to `ACTIVE`; no state guard on the status endpoint — routes_vendor.py:71,84
- §3.4 — insert — ambiguity — `vendor_id: ""` treated exactly as omission — routes_workorder.py:134
- §3.4 — revise — ambiguity — IN_HOUSE with supplied `vendor_id` → 400, checked before the safety-critical gate, both after the `PENDING_DISPATCH` guard — routes_workorder.py:144
- §3.4 — revise — mismatch — the market check is not an eligibility clause; exactly four clauses; `ERR_MARKET_MISMATCH` fires at rank 160 ahead of state guard, channel fork and all clauses (incl. IN_HOUSE) — routes_workorder.py:138, calc.py:386
- §3.4 — insert — ambiguity — the work order under test is excluded from the per-date capacity sum even when already dispatched to that vendor — calc.py:368
- §3.4 — insert — ambiguity — fourth sort key: insertion order on `created_at` ties, making the ranking total — calc.py:417
- §3.4 — insert — ambiguity — `excluded_vendor_ids` in register scan order; the ranking read has no state/channel precondition and raises no eligibility error — calc.py:404, routes_workorder.py:120
- §3.5 — revise — mismatch — channel picks the origin status but both roles are authorized; rank-352 applies only to `Vendor`, so an `OperationsManager` may complete a vendor-channel row (crew days still released) and a `Vendor` on an in-house row always gets `ERR_NOT_ASSIGNED_VENDOR` — routes_workorder.py:195
- §3.5 — revise — ambiguity — make-ready trigger needs the project still `IN_PROGRESS`, so a `SCOPING` drained queue does not cascade and `RENT_READY` never re-fires — cascades.py:196
- §3.5 — revise — mismatch — hop 3 conditional on the home still `RENOVATING`; deleted a bogus "excess of booked showings" posture input; `hold_sell_score_bps`/`disposition_flagged` live on the **home**, and the hop is a no-op with no `APPROVED` case — cascades.py:219,80
- §3.8 — insert — ambiguity — zero `verified_monthly_income_cents` pins `rent_to_income_bps` at sentinel `1000000000` — calc.py:244

### Pass 3 — routes_prospect.py, routes_leasing.py, routes_compliance.py
591 lines both sides, 132,253 → 135,990 bytes. **11 ambiguity-pins, 5 mismatch-revisions** (16 edits).
- §2.1 — revise — mismatch — a rental application's `prospect_id` is never compared to `X-User-ID`; pins the only two comparisons (booking payload, cancellation's stored id) — routes_prospect.py:208,232
- §2.7 item 21 — insert — ambiguity — added **rank 151** for `ERR_DUPLICATE_PROSPECT_EMAIL`, below rank 50 so unknown-market wins — routes_prospect.py:47-50
- §2.7 item 37 — revise — mismatch — rank 354 fires on slot **booking** and cancellation, never in screening — routes_prospect.py:209,233
- §3.6 — insert — ambiguity — email uniqueness is exact string equality, no case folding/trimming — routes_prospect.py:48-50
- §3.6 — insert — ambiguity — no ownership comparison on the verification path; `document_match_score_bps`/`device_reputation_bps` capped at 10000; `ip_geo_distance_km` a whole count; all six signals mandatory — routes_prospect.py:32-40,97
- §3.6 — revise — mismatch — transition list omitted the `REJECTED` → `REJECTED` self-loop; impl has no state guard — routes_prospect.py:110
- §3.7 — insert — mismatch — booking check order is market, slot state, ownership, identity, fraud, posture (narrative order contradicted impl) — routes_prospect.py:204-215
- §3.7 — insert — ambiguity — a `Prospect` cancelling an `AVAILABLE` window gets `ERR_NOT_SLOT_OWNER`, not `ERR_UNAUTHORIZED` — routes_prospect.py:232-233
- §3.8 — insert — ambiguity — `lease_term_months` must be ≥ 1 when supplied — routes_leasing.py:21
- §3.8 — revise — mismatch — `ERR_DUPLICATE_APPLICATION` is checked first (rank 158), not last; the four narrated rules run in rank order — routes_leasing.py:33-49
- §3.8 — insert — ambiguity — deposit `amount_cents` must be at least 1 — routes_leasing.py:205
- §3.9 — insert — ambiguity — the tax-appeal conditional requirement is a rank-10 `ERR_INVALID_REQUEST` before role checks; values on other types stored as 0; `consultant_fee_bps` stored whatever the type; the obligation's `assessed_value_cents` copy is never used in the savings math — routes_compliance.py:34-38,57-60
- §3.9 — insert — ambiguity — an omitted `work_order_id` on a re-plan leaves the existing link — routes_compliance.py:119-120
- §3.9 — insert — ambiguity — `evidence_ref` with an appeal is stored; `settled_value_cents` on a non-appeal is ignored — routes_compliance.py:143-148
- §3.9 — insert — ambiguity — `review_note` accepted but never persisted and in no response field — routes_compliance.py:159
- §3.9 — insert — ambiguity — only `REJECT` clears `submitted_by_user_id` — routes_compliance.py:179,185

### Cumulative
PRD_FINALIZED.md 586 lines / 120,909 bytes → **PRD_COMPLETED.md 591 lines / 135,990 bytes** (+5 lines, +15,081 chars). **53 edits total: 40 ambiguity-pins, 13 mismatch-revisions.** No new sections.

Pass-3 integrity check: 5 top-level sections in order; file ends newline-terminated on the `ERR_YIELD_BELOW_FLOOR` row; 68 impl routes ↔ 68 §4 rows, set-equal after path-param normalisation; all 70 `errors.py` ids present in §5 with matching statuses and verbatim descriptions (sole diff: backticks around `X-User-Role`, pre-existing); §2.7 ladder numbering unbroken 1–70; pass-1/pass-2 hunks all verified surviving.

**Orchestrator verification:** PRD_COMPLETED.md is NOT byte-identical to PRD_FINALIZED.md (52 diff hunks — so all three passes really ran); `find` confirms no file under `implementation/`, `test_suite/`, or `test_helpers/` was modified after the 05:16 green sweep, so the 8×82/82 evidence still describes the shipped code.

## Pipeline complete — 2026-09-04T05:54:47.240Z

All 9 steps done. Final artifacts: SCAFFOLD.yaml, SCAFFOLD_DIFFICULTY_DESIGN.yaml, SCAFFOLD_CORNER_DESIGN.yaml, test_helpers/ (9 files), test_suite/ (conftest + 30 files, 82 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (17 modules + start.sh), results.1..8.json all 82/82}.
