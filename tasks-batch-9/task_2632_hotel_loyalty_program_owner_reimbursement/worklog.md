# Worklog — task_2632_hotel_loyalty_program_owner_reimbursement

## Step 1: Create task directory — 2026-09-03T22:35:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2632_hotel_loyalty_program_owner_reimbursement` and its `workspace/` subdirectory. Index 2632 was pre-assigned by the invoking pipeline; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate Scaffold — 2026-09-04T00:49:00.000Z

Scaffold generation for `task_2632_hotel_loyalty_program_owner_reimbursement` is complete. All three files are on disk, YAML-valid, and the linter is clean.

**Files**
- `SCAFFOLD.yaml` — 14 entities, 9 state machines, 2 §1.2.1 concurrency rules, 19 calculations, 59 ordered validations, 69 endpoints, 59 errors, 5 roles. `complexity_profile`: `role_model: segregation_of_duties`, `consistency_model: immediate`, layers `[dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency, derived_field_reconciliation]`. Neither design key present.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1591 lines, single key `scaffold_difficulty_design`: **9 rules / 19 instances**.
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4248 lines, single key `scaffold_corner_design`: **9 sections / 77 instances** (57 with full test recipes, 20 `excluded_because` stubs) — entities 11, state_machines 15, calculations 13, validations 11, endpoints 7, errors 8, rbac 5, cross-cutting complexity layers 6, consistency model 1.

**Verification**
- `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (883 calls scanned across §1.8+§1.9; 69 endpoints, 14 entities.)
- Error coverage: all **59/59** declared error ids are triggered somewhere in §1.8/§1.9 (the last two, `ERR_STALE_HOTEL_VERSION` / `ERR_STALE_MEMBER_VERSION`, land in the two mandatory `optimistic_concurrency` instances).
- 96 instance names across §1.8 ∪ §1.9, zero duplicates; every stub cites a real §1.8 instance and carries no `test_recipe`; sections appear in the exact required order; no forbidden concurrency vocabulary anywhere in the three files.

**Key design adjudications**
1. Validation 40 (hotel status) split so FEE_DELINQUENT properties still accept stays and reimbursement batches — only PEAK award inventory is withdrawn — and so activate/terminate have their own declared errors.
2. The batch delinquency surcharge is program-fund revenue, never a credit to the hotel's fee ledger.
3. Release/approve/pay are all ProgramAdministrator; separation is enforced on `X-User-ID` by priority 4 (`ERR_SEGREGATION_OF_DUTIES`) and priority 5 (`ERR_PAYER_CONFLICT`), giving three distinct operators.
4. Complaint adjudication moves no points; goodwill is a separate adjustment and requires a non-IMPAIRED fund.
5. `Member.enrollment_date` keeps a documented clock-based default (`2026-08-01T00:00:00Z` logical clock).
6. A stay void waives its own OBLIGATED **and** ESCALATED deliveries (hop 5), which is what makes `ERR_DELIVERY_NOT_ESCALATED` reachable.
7. The redemption-pricing `created_at` tie-break is unreachable (validation 74 forbids same-hotel/same-season window overlap), so only PEAK-over-STANDARD ranking is tested.
8. `request-info` is MemberCareAgent-exclusive (refused even to the administrator) while `provide-info` is shared.
9. Priority 41 (`ERR_STAY_INVALID_STATE`) deliberately masks 42 on a voided stay's waived delivery; 42 is triggered instead via a SETTLED delivery.
10. The delinquency trigger is a strict `>` on 250000 cents and is one-directional: adjusting back down to exactly the threshold leaves the property FEE_DELINQUENT (only a paid batch restores ACTIVE) — this is the `rate_threshold_triggers` corner.
11. Program fee is rounded per stay before summing, so a restatement replaces 617 with 1235 (`round_half_up(1234.5)`) rather than re-rounding a new total — the `derived_field_reconciliation` corner.
12. List `total_count` is asserted in prose with a `<name>_page: $.data` capture, because the linter rejects `$.data.total_count` captures on `Entity[]` endpoints.

## Step 3: Copy Shared Files — 2026-09-04T00:49:30.000Z

Copied `./INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T01:08:00.000Z

PRD generation for task 2632 is complete.

**Output:** `workspace/PRD.md` — 466 lines, ~15,850 words. Written incrementally (Write + 8 heredoc appends); the file ends at a genuine boundary (final row of the §5 error table), verified with `wc -l` and `tail`.

**Section list**
- §1 Introduction
- §2 Global Specifications & System-Wide Principles — 2.1 Operator Identity and RBAC · 2.2 API Response Structure (verbatim block) · 2.3 Pagination and Collection Filters · 2.4 Common Resource Properties · 2.5 The Logical Programme Clock · 2.6 Identifier Resolution and the Order of Validation · 2.7 Money, Points and Rounding Discipline · 2.8 Optimistic Concurrency · 2.9 Cascade Integrity and Conserved Quantities · 2.10 Segregation of Duties · 2.11 Fund Solvency Posture as a Programme-Wide Gate (11 subsections)
- §3 Business Logic & Workflows — 3.1 Property lifecycle · 3.2 Award prices and blackout calendar · 3.3 Members and the paid-stay posting fork · 3.4 Disputes, adjustments and voids · 3.5 Elite benefit obligations, delivery and cost recovery · 3.6 Booking, pricing and fulfilling an award stay · 3.7 Owner reimbursement accrual to disbursement · 3.8 Point sales, partner volume and liability valuation · 3.9 Complaints, review loop and adjudication (9 subsections)
- §4 Endpoint Definitions (4-column table) · §5 Error Code Catalogue (2-column table)

**Hard Contract results (machine-verified against SCAFFOLD.yaml with a YAML-driven script, code fences excluded from token extraction):**
- **Contract 1 — Field-Name Coverage: PASS.** All 14 entities' fields present verbatim in backticks (0 missing); `id`/`created_at`/`updated_at`/`version` present; all 69 endpoints' `request_body` / `query_params` identifiers present (0 missing); all 13 path variables present as bare identifiers; all enum values across every constrained field present (0 missing); all 5 role names present.
- **Contract 2 — Rule Coverage: PASS.** All 59 validation error IDs appear in §1–§3 prose (not only in §5); all 48 state-machine transitions across the 9 machines described, including both Redemption dimensions; all 19 calculations expressed in prose with every constant value present (0 constants unfound); both `concurrency_rules` (OCC fields, mismatch errors, 412); both conserved quantities with all three scoped-zero identities; `applies_to` scopes and sibling-branch symmetry (qualifying/non-qualifying posting, goodwill/upheld resolution, delivery-ordered/denial-upheld adjudication, accrual/settlement reimbursement variants, provisional/final bonus tier variants).
- **Contract 3 — §3 Path Purity: PASS.** 0 violations: no backtick token inside §3 starts with `/`, is a bare HTTP method, or combines method+path. All 69 method/path pairs and role lists in §4 diffed against the scaffold — exact match after correcting two role lists (`GET /loyalty/hotels/{hotelId}` gains MemberCareAgent; `GET /loyalty/hotels` is admin/auditor only).

**Style:** no pseudocode operators (`>=`, `IN`, `floor()`, `+=`, `round_half_up`) survive anywhere in the file; no fuzzy qualifiers; no "and so on" elisions; no audit footer in PRD.md.

**Scaffold contradictions resolved (worth flagging to the test-suite generator so asserts match):** (1) fee-ledger settlement on batch pay follows `program_fee_assessment` step 2 — only `fee_offset_base_cents` of PAID batches is subtracted, so the surcharge is retained by the fund and a 700,000 ledger with a 7,000 surcharge lands at exactly 0, not −7,000; (2) `FEE_DELINQUENT → ACTIVE` fires at a balance **at or below zero** (state machine), not "at or below 250000" (pay endpoint blurb); (3) the co-brand bonus entry on purchase settle is `EARN_BONUS` (state machine + `source_purchase_id` description), not "a second PURCHASE entry"; (4) `program_fee_pct` range taken as 0.0–0.20 with ≤4 decimals (validation 24), not [0,1] (error catalogue); (5) deliver/deny evaluate the stay's status (priority 41) before the delivery's status (priority 42), per priority order rather than state-machine listing order.

**Orchestrator truncation check:** `tail -15` confirms the file terminates on the `ERR_FUND_IMPAIRED_PEAK_BLOCKED` error-table row — a real section boundary, not mid-sentence. No regeneration needed.

## Steps 5 & 6: Launched concurrently — 2026-09-04T01:10:00.000Z

Step 5 (`prd-bench-unit-test-generator` → `test_helpers/` + `test_suite/`) and Step 6 (`prd-bench-implementation-generator` → `workspace/implementation/`) were launched as two background subagents. Step 6 was given an explicit hard prohibition on reading `test_suite/` / `test_helpers/` in addition to the physical isolation of not-yet-existing directories, and both were forbidden from reading sibling task directories. Summaries are appended below as each returns.

## Step 6: Generate Implementation — 2026-09-04T01:41:00.000Z

Implementation complete and verified.

## Files written
All under `workspace/implementation/`:

| File | Lines |
|---|---|
| `app.py` | 88 |
| `db.py` (in-memory store, logical clock, id/version stamping) | 219 |
| `errors.py` (error_id → HTTP status + default message table) | 150 |
| `middleware.py` (auth, role gate, owner/member scoping) | 86 |
| `response.py` (envelope, `api_request_id`, pagination meta) | 94 |
| `support.py` (created/one/listing helpers) | 52 |
| `validate.py` (shape, range, enum, FK, date validators) | 287 |
| `services/calc.py` (19 calculations, all `Decimal`) | 349 |
| `services/derive.py` (re-derivation, ledger, fund, obligations) | 369 |
| `routes/hotels.py` | 404 |
| `routes/members.py` | 113 |
| `routes/stays.py` | 346 |
| `routes/redemptions.py` | 468 |
| `routes/points.py` | 230 |
| `routes/complaints.py` | 227 |
| `routes/__init__.py`, `services/__init__.py` | 0, 0 |
| `start.sh`, `requirements.txt` | launcher + `flask>=2.0.0` |

Total 3482 lines of Python. Every module parses under `ast.parse`. `__pycache__` removed so the harness always boots from source.

**Endpoint count: 69** — exactly the declared surface, enumerated from the live Flask `url_map` (68 business endpoints + `POST /_clock/set_current_utc`).

## Verification
Full end-to-end smoke run against `PORT=18632 bash start.sh` exercised: hotel create → rate plan → activate → award pricing → member → elite-qualifying stay → post (member reaches GOLD, 2 obligations synthesised) → second stay post (base 1234, bonus 617, fee 586) → co-brand purchase 100000 (cash 110000, bonus 10000) → settle → fund HEALTHY → award booking (76000 points, 2 nights, GOLD free-night applied) → confirm → complete-stay (accrual estimate 45000) → batch open → release (gross 45000, surcharge 487, offset 24823, net 20177) → SoD rejection → approve → payer-conflict rejection → pay → hotel fee ledger cleared, fund cash 89823 → benefit deny → complaint file/review/request-info/provide-info/resolve/escalate/adjudicate (DELIVERY_ORDERED ⇒ delivery DELIVERED with cost recovery 4500) → goodwill adjustment → ledger/list reads → 401/403/404 negative paths → stay void (entries reversed, balance re-derived, obligations waived). Server killed by PID from `lsof -ti :18632`; port confirmed free. No broad `pkill` was used at any point.

## PRD ambiguities resolved
1. **`Hotel.reimbursement_owed_cents` basis** — the scaffold's side-effect prose implied accrued (estimated) amounts, but §2.9 and the field's own description define it as settled. Chose Σ `settled_reimbursement_cents` over bookings in `BATCHED`/`PAID`, i.e. amounts owed only once a release has fixed them.
2. **Settle bonus ledger entry type** — scaffold prose said "a second `PURCHASE` entry"; the PRD ledger enum reserves `EARN_BONUS` for bonus points. Wrote the main entry as `PARTNER_SALE`/`PURCHASE` by channel and the bonus as `EARN_BONUS`.
3. **Award pricing window overlap** — the PRD does not forbid two windows covering one check-in date. Deterministic selection: `PEAK` before `STANDARD`, then oldest `created_at`, then insertion sequence.
4. **Blackout scope vs season** — a `STANDARD_ONLY` window is skipped when the resolved season is `PEAK`; `ALL` windows always bite. Any night of the stay intersecting an `ACTIVE` window refuses the booking.
5. **Batch eligibility keying** — bookings are attached by `month_key(checkout_date) == period_month` and must be `STAYED` + `ACCRUED`; the accrual estimate at complete-stay and the settlement figure at release are computed independently (dual-variant), with occupancy/ADR snapshotted onto the batch at release.
6. **Fee-ledger sign after a void** — voiding a stay whose fee had already been offset by a paid batch leaves the re-derived ledger negative (observed −586). Re-derivation is never clamped, since the PRD defines the balance as assessed minus offsets rather than a monotone counter.
7. **Complaint/delivery coupling** — `related_delivery_id` is persisted only when `subject_type == BENEFIT_DENIAL`; a benefit-denial complaint with no delivery, or with one belonging to another member's stay, both yield `ERR_DELIVERY_MEMBER_MISMATCH`.
8. **Void waives its own obligations** — beyond the tier-fall waiver cascade, a voided stay's own `OBLIGATED` and `ESCALATED` deliveries are waived, since an obligation cannot outlive the stay that created it.

## Step 5: Generate Unit Tests — 2026-09-04T03:45:00.000Z

**Orchestrator note on an interruption.** The Step 5 subagent was terminated by a transient upstream API error partway through its final test file. Per the resume-not-respawn rule, the orchestrator audited the on-disk state (all 9 helpers + conftest + test_01..test_18 parsed; 19/19 difficulty instances and 52/57 non-stub corner instances already tagged; zero bogus tags, zero stub tags), computed the exact 5-instance remainder, and resumed **the same agent** via SendMessage with that to-do list rather than spawning a fresh one — a fresh agent would have re-derived helper conventions and made the suite diverge from itself. The agent finished the remainder into a new `test_19_*.py`, leaving `test_18` and `test_helpers/` untouched. Its full-deliverable summary follows verbatim.

Step 5 is complete. `test_19` is finished and the whole deliverable now audits clean.

## What I did in this resumption

Appended the three remaining classes to the new file `test_suite/test_19_concurrency_thresholds_reconciliation_and_immediate_visibility.py` (chunked `cat >>` heredocs; `test_18` untouched, `test_helpers/` untouched):

- `TestFeeLedgerAtExactlyTheThresholdStaysActiveAndOneCentMoreDoesNot` — 5 tests
- `TestHotelFeeLedgerReconcilesAfterCreateAdjustAndVoidOfItsSources` — 5 tests
- `TestOnePostingIsAlreadyVisibleInEveryDerivedReadThatFollowsIt` — 6 tests

Two defects caught and fixed before finishing: five class-E citations were paraphrases (replaced with verbatim PRD sentences from the liability/earning/fund paragraphs, all re-cleared by whitespace-normalised substring match), and one `assert_member(lifetime_points=...)` kwarg that does not exist (`lifetime_points_earned`). I then ran a static signature check of every `fx.*`/`fac.*`/`assert_*`/`api_client.*` call across all 19 files against the real helper signatures — 0 problems.

Verification: `ast.parse` OK; `pyflakes` clean on all 19 test files plus all 9 helpers; `pytest --collect-only` collects 333 items (332 functions, one parametrized into 2); audit script reports `tests=332 bad=0 distinct_tags=76`.

## Full Step 5 deliverable

`test_helpers/` (9 files, 3 270 lines): `__init__.py` 245, `api_client.py` 412, `api_errors.py` 134, `assertions.py` 663, `constants.py` 130, `factories.py` 224, `fixtures.py` 987, `test_users.py` 61, `types.py` 414.

`test_suite/` (conftest + 19 test files, 13 330 lines, 332 tests):

| file | lines | tests |
|---|---|---|
| conftest.py | 75 | – |
| test_01_stay_earning_and_fee_arithmetic.py | 431 | 11 |
| test_02_award_pricing_and_inventory.py | 548 | 12 |
| test_03_reimbursement_batch_waterfall.py | 490 | 12 |
| test_04_hotel_lifecycle_cascades.py | 689 | 16 |
| test_05_booking_refusal_priority.py | 498 | 11 |
| test_06_benefits_complaints_and_point_sales.py | 508 | 12 |
| test_07_entity_shape_and_declared_defaults.py | 1003 | 25 |
| test_08_lifecycle_entry_and_forward_transitions.py | 639 | 14 |
| test_09_wrong_state_refusals_and_clock_gates.py | 893 | 23 |
| test_10_earning_fee_and_recovery_derivations.py | 636 | 18 |
| test_11_award_window_ranking_purchase_tiers_and_liability.py | 494 | 15 |
| test_12_boundary_acceptance_and_refusal_precedence.py | 905 | 24 |
| test_13_uniqueness_scopes_caps_and_onboarding_gates.py | 949 | 25 |
| test_14_member_surface_action_responses_and_the_computed_fund.py | 521 | 16 |
| test_15_resolution_arms_reverse_filters_paging_and_ignored_input.py | 844 | 25 |
| test_16_settled_row_refusals_cash_gated_payment_and_the_error_envelope.py | 666 | 18 |
| test_17_administrator_exclusives_care_queue_and_peer_scoping.py | 668 | 19 |
| test_18_three_operator_duty_split_and_header_authentication.py | 354 | 10 |
| test_19_concurrency_thresholds_reconciliation_and_immediate_visibility.py | 1019 | 26 |

## Coverage — 76/76, exact 1:1

- Queue A (§1.8 difficulty): **19/19** non-stub instances. Set-diff against the yaml: no missing, no extra tags.
- Queue B (§1.9 corner): **57/57** non-stub instances (20 `excluded_because:` stubs correctly not emitted). Set-diff against the yaml with true section keys: no missing, no extra.
- Every test carries exactly one `Design:` line as the last docstring line and exactly one verbatim `PRD: "..."` citation of ≥8 words; zero bogus tags, zero stub tags, zero untagged tests.

## Instances skipped — none

No instance was dropped for PRD silence or non-derivability. Seven **assertion-level** claims inside otherwise-emitted instances were dropped or corrected (all recorded here for the worklog):

1. `2026-13` batch-period shape refusal — not uniquely derivable (PRD never states the period-format refusal); assertion dropped.
2. "No PUT/PATCH/DELETE on the member resource" — design-document-only claim, no PRD sentence; dropped.
3. "Every response carries `meta.api_request_id`" — design-document-only; dropped.
4. The input-ignored instance's `is_qualifying: true` smuggle — proves nothing on a TRANSIENT plan (that value is already true); replaced with the stronger `is_qualifying=False, program_fee_eligible=False, counts_toward_elite=False` smuggle.
5. "The hotel `version` moves on every ledger re-derivation" (in `hotel_fee_ledger_reconciles_after_create_adjust_and_void_of_its_sources`) — the PRD increments the hotel version only on delinquency transitions, performance refresh, activation, termination and award booking, never on a plain posting/void; not uniquely derivable, assertion dropped.
6. Same instance's `qualifying_nights_ytd == 2` — contradicted by the PRD (nights count only for `POSTED_QUALIFYING`, and `ADJUSTED` explicitly "sits outside the tier-counting set"); emitted as `== 0` with an explanatory message.
7. `fee_ledger_at_exactly_the_threshold...`'s "the property can still take stays while FEE_DELINQUENT" — contradicted by the exactly-`ACTIVE` stay-capture rule; only the batch-opening half is asserted (PRD: booking an award stay and opening a batch accept `ACTIVE` or `FEE_DELINQUENT`).

Two earlier corrections also worth carrying: blackout scope `PEAK_ONLY` does not exist in the PRD (used `STANDARD_ONLY`), and restating breakage does **not** touch `last_revalued_at` (asserted as still null in the immediate-visibility class).

**Orchestrator independent verification:** re-ran the design-tag audit myself against both yaml indices — difficulty 19/19, corner 57/57, 332 tagged tests / 76 distinct tags, zero bogus tags, zero stub-instance tags. All 9 helpers and all 20 test-suite files parse; `pytest --collect-only` collects 333. `test_helpers/` and `test_suite/` are both at the task root (not under `workspace/`), so no relocation was needed.

## Step 7: Run Tests and Iterate — 2026-09-04T04:25:00.000Z

All 8 rounds are green. Final state: **333 total / 333 passed / 0 failed / 0 errors** in each of the 8 parallel rounds (≈616 s per round), run under `setsid nohup` per the required command.

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (plus one targeted single-round subset run mid-iteration-1 for fast feedback; the subset dir was deleted before the final sweep). Baseline sweep was perfectly deterministic across all 8 rounds (333 total / 271 passed / 7 failed / 55 errors), so there was no flakiness or load-induced noise to filter — every failure was a real defect.

**Tests deleted:** none. Every failing test was traceable to a verbatim PRD sentence and was either faithful (implementation bug) or mis-translated the sentence (test bug). One assertion was removed under STEP 1c partial coverage, described below.

**Fixes applied to `test_helpers/`:** none. The fixture-name defect that produced all 55 setup errors lived in `test_suite/`, not in the helper layer.

**Fixes applied to `test_suite/`:**
- `test_17_administrator_exclusives_care_queue_and_peer_scoping.py`, `test_18_three_operator_duty_split_and_header_authentication.py`, `test_19_concurrency_thresholds_reconciliation_and_immediate_visibility.py` — word-boundary rename of the fixture parameter `api_client` → `api` (81 / 48 / 147 occurrences). `conftest.py` declares `api`; there is no `api_client` fixture, so all 55 `errors` were `fixture 'api_client' not found` setup failures.
- Same three files, 21 `validate_error(...)` call sites — dropped a third positional argument. The framework signature is `validate_error(response, expected_error_id, expected_status: int | None = None)`; these sites passed a human-readable prose string there, which is truthy and got compared against `response.status_code`, producing `Expected HTTP <prose> for 'ERR_X', got 403`. Removing the argument makes the framework fall back to its registered `error_id → HTTP status` cross-check, so the assertion is strictly stronger, and the exact `error_id` assertion is untouched.
- `test_09_wrong_state_refusals_and_clock_gates.py::assert_hotel` (~line 889) — `reimbursement_owed_cents` 45_000 → 0. PRD §2.9 defines the figure as "the sum of `settled_reimbursement_cents` across that property's award bookings whose `reimbursement_status` is either `ACCRUED` or `BATCHED`", and the settlement figure is only written at release, so an accrued-but-unbatched night contributes 0. Corroborated by test_18 asserting 6_000 only once the booking is BATCHED with `settled_cents=6_000`.
- `test_04_hotel_lifecycle_cascades.py::test_the_row_the_batch_held_is_voided_and_unlinked_on_the_way` — removed only the `settled_cents=0` assertion (STEP 1c). PRD §3.1's termination cascade names solely "reverts `BATCHED → VOIDED` with its `batch_id` cleared to null"; the `settled_reimbursement_cents` reset appears only in §3.7's ordinary-rejection branch. BRANCH-ASYMMETRIC SIDE EFFECT; the status, `estimated_cents` and `batch_id is None` assertions were kept.
- `test_19_...py::test_one_further_cent_of_fee_flips_the_property_into_delinquency` — `base_points=0` → `base_points=2`. PRD §3.4 qualifying arm: base points are `room_revenue_cents × base_earn_rate_per_dollar ÷ 100` rounded down; the 20-cent night on the TRANSIENT plan's 10 points/dollar earns exactly 2, not 0. The docstring's own claim (a 20-cent stay assessing 1 cent of fee) is unaffected.

**Fixes applied to `workspace/implementation/`:**
- `response.py` — new `_page_int()`, rewritten `page_params()`. Pagination parameters were silently clamped; PRD §2.3 declares `limit` "accepts a minimum of 1 and a maximum of 100" and §2.6's request-shape step makes an out-of-domain value `ERR_INVALID_REQUEST` (HTTP 400) rather than a quiet substitution. Added `from errors import ApiError` (no cycle — `errors.py` imports nothing local).
- `services/derive.py` — `recompute_member()` now counts `PENDING` and `SETTLED` purchases toward `points_purchased_current_year`, and `recompute_partner()` delegates to the existing `partner_month_consumption()` (same PENDING+SETTLED rule) for `purchased_points_mtd`. PRD §3.8: "The `points_quantity` is nevertheless added to the member's `points_purchased_current_year` and, for a partner sale, to the partner's `purchased_points_mtd`, so both caps are consumed by the pending purchase and cannot be defeated by leaving purchases unsettled." This specific-case sentence overrides §2.9's generic SETTLED-only phrasing; independently corroborated by test_17 (20_000 on a PENDING purchase) and test_06 (0 after refund).
- `routes/points.py::create_purchase()` — re-derives the member and, when present, the partner immediately after the pending purchase row is stored, so both cap counters are visible on that same request (PRD §3.8).

Storage remains in-memory only (`db.Store` dicts keyed by id); no file, SQLite or `/tmp` persistence, and no startup seeding, so each `start.sh` re-invocation under `--isolation per-test-server` boots empty.

**Orchestrator independent verification:** read all 8 `results.$i.json` myself — every round reports `total=333, passed=333, failed=0, errors=0`, durations 615.9–616.5 s, all written at the same timestamp (04:25), so the sweep genuinely ran to completion under setsid rather than being reaped. Also confirmed: zero `mark.skip` / `mark.xfail` / `pytest.skip` occurrences anywhere in `test_suite/` or `test_helpers/`; zero `sqlite` / `json.dump` / file-write / `/tmp` references in `implementation/`; design-tag audit still 332 tagged tests across all 76 non-stub instances (no test was lost).

Step 8 is NOT skipped: Step 7 applied 3 `implementation/` fixes and 5 `test_suite/` fixes across 2 iterations.

## Step 8: Finalize PRD — 2026-09-04T04:33:00.000Z

All six edits are in place. Verification: `PRD.md` and `PRD_FINALIZED.md` are both **466 lines**; `PRD_FINALIZED.md` ends on the same real section boundary — the final `| ERR_FUND_IMPAIRED_PEAK_BLOCKED | 402 |` row of the §5 error table.

## Line counts / delta
- `PRD.md`: 466 lines / 113,377 bytes
- `PRD_FINALIZED.md`: 466 lines / 115,231 bytes
- **Line delta: 0 (0.00%); byte delta +1,854 (+1.64%)** — every edit is an inline expansion inside an existing paragraph, so no line was added or removed.

## Changes (one bullet each)

- **§2.3** — revise — pinned `offset` as minimum 0 with no maximum (past-the-end is a legal empty page), and pinned that an out-of-domain or non-integer `limit`/`offset` is refused `ERR_INVALID_REQUEST` (400) under §2.6's request-shape step rather than clamped or defaulted (`limit` 0 / 101 / negative `offset`) — `implementation/response.py:56-81`
- **§2.9** — revise — `points_purchased_current_year` and `purchased_points_mtd` now count purchases whose `status` is **`PENDING` or `SETTLED`** (only `REFUNDED` leaves the set), replacing the SETTLED-only phrasing — `implementation/services/derive.py:182-190, 220-231, 234-239`
- **§3.1 (termination cascade)** — insert — pinned that the termination write-off does **not** borrow §3.7's resets: the rejected batch keeps its six released money figures, and every booking the cascade voids keeps both `estimated_reimbursement_cents` and `settled_reimbursement_cents` — `implementation/routes/hotels.py:137-152`
- **§3.6 (complete-stay)** — insert — pinned that the `reimbursement_owed_cents` recomputation picks up `settled_reimbursement_cents`, which is unwritten until release, so a merely-`ACCRUED` booking contributes 0 regardless of its estimate — `implementation/routes/redemptions.py:212-218` + `services/derive.py:265-271`
- **§3.7 (release)** — revise — replaced the false claim "though its value does not change" with the accurate statement that the owed figure now picks up each item's newly written `settled_reimbursement_cents` (previously 0) — `implementation/routes/redemptions.py:359-384`
- **§3.8 (Partners)** — revise — `purchased_points_mtd` derives from `PENDING` **or** `SETTLED` purchases, and that same figure is what the monthly cap is measured against — `implementation/services/derive.py:220-239` + `routes/points.py:87-90`

## Per-edit pre-edit search log

**Edit 1 — §2.3 pagination**
(a) Subject: how `limit`/`offset` are parsed and enforced on every collection endpoint.
(b) Enumerated: `response.py::_page_int/page_params/collection_response`; `grep -rn "page_params\|collection_response\|request.args"` across all of `implementation/` → the *only* consumer of `page_params()` is `collection_response()`, itself the only list-response builder (`support.py::listing` → `collection_response`); all 20+ list routes go through `support.listing`. Also read `support.py::query_filters` (equality filters, unaffected) and `middleware.scope_filter` (ownership scoping runs before paging, no interaction).
(c) Adjustment: wrote "a parameter that is supplied but is not a whole number, or whose value falls outside the range declared for it" rather than naming only `limit`, because `_page_int` applies the identical rule to `offset` with a `None` maximum; explicitly noted `offset` has *no* maximum so the sentence does not imply a 100-row ceiling on `offset`. Added "an `offset` that skips past the end ... is a legal empty page" so the new refusal language cannot be read as forbidding the empty-window case the impl allows.

**Edit 2 — §2.9 purchase counters**
(a) Subject: the counted status set for `Member.points_purchased_current_year` and `Partner.purchased_points_mtd`.
(b) Enumerated: `derive.py::recompute_member` (PENDING+SETTLED, `year_of(created_at)`), `derive.py::member_purchase_consumption` (identical rule, used for the annual cap gate), `derive.py::partner_month_consumption` (PENDING+SETTLED, `month_key_of(created_at)`), `derive.py::recompute_partner` (delegates to it), and every caller: `points.py::create_purchase` (87-93, 113-115), `settle_purchase` (156-162), `refund_purchase` (183-189); plus `calc.PURCHASE_STATUSES` to confirm the status universe is exactly PENDING/SETTLED/REFUNDED. Also `db.apply_derived` to confirm the counter write is a version-bearing mutation only when the value moves.
(c) Adjustment: phrased the exclusion as "only a `REFUNDED` purchase leaves the counted set" (safe given the three-value status universe) instead of an open-ended list; deliberately left §3.8's settle/refund "are all recomputed" sentences untouched, since "recomputed" stays true even where PENDING→SETTLED moves no value.

**Edit 3 — §3.1 termination retention**
(a) Subject: which fields the termination cascade resets vs retains on rejected batches and voided bookings.
(b) Enumerated: `hotels.py::terminate_hotel:129-152` (ACCRUED→VOIDED sets status only; BATCHED→VOIDED sets status + `batch_id=None`; batch gets `status`/`rejection_reason` only) contrasted against `redemptions.py::reject_batch:417-433` (resets `settled_reimbursement_cents` and all six batch money fields) and `pay_batch:456-460` (retains). Also `derive.py::recompute_hotel:265-271` to confirm `VOIDED` drops out of the owed set on status alone, and `create_redemption:139-140` / `release_batch:365-367` for where the two figures are written.
(c) Adjustment: scoped the claim to "every award booking **this cascade** voids" so it covers both the ACCRUED and BATCHED branches without asserting anything about `reject_batch`; framed the batch clause as "retains every figure the release wrote" so it stays true for an OPEN batch whose fields were already 0, and left §3.1's pre-existing "lands at 0" sentence untouched (out of scope).

**Edit 4 — §3.6 complete-stay owed recomputation**
(a) Subject: the value `Hotel.reimbursement_owed_cents` takes when a booking reaches `ACCRUED`.
(b) Enumerated: `derive.py::recompute_hotel:265-271` (the single definition, summing `settled_reimbursement_cents` over ACCRUED+BATCHED) and every `recompute_hotel` callsite that could observe it — `redemptions.py::complete_redemption:218`, `release_batch:384`, `reject_batch:436`, `pay_batch:464`, `hotels.py::terminate_hotel:186`, `activate_blackout:366`, `revoke_blackout:384`, plus `stays.py` posting/adjust/void paths; and `calc.owner_reimbursement`/`reimbursement_rate_per_night` to confirm `estimated_reimbursement_cents` is written independently at accrual.
(c) Adjustment: said the accrued booking "contributes 0" rather than "the figure does not move" — other bookings of the same property may already be BATCHED with nonzero settled figures, so a claim about the whole field would be false off the Step 7 site.

**Edit 5 — §3.7 release owed recomputation**
(a) Subject: the same field's behaviour at batch release.
(b) Enumerated: `redemptions.py::release_batch:359-384` (writes `settled_reimbursement_cents` per item, then `recompute_hotel`), `derive.py::recompute_hotel:265-271`, and `calc.owner_reimbursement` → `reimbursement_rate_per_night` (can legitimately return 0 when `adr_cents` is 0 and occupancy >= 0.80).
(c) Adjustment: because a zero-ADR property makes the settled figure 0, I avoided "the figure rises"/"the value changes" and instead wrote that the recomputation "picks up each item's newly written `settled_reimbursement_cents` where that field previously stood at 0" — true in the degenerate case as well.

**Edit 6 — §3.8 Partners paragraph**
(a) Subject: the derivation of `Partner.purchased_points_mtd` and the figure the monthly cap tests against.
(b) Enumerated: `derive.py::partner_month_consumption:220-231`, `derive.py::recompute_partner:234-239`, `points.py::create_purchase:87-90` (cap gate reads `partner_month_consumption`, i.e. the same PENDING+SETTLED figure), `settle_purchase:159-162`, `refund_purchase:186-189`, and `points.py::create_partner:39` (opens at 0).
(c) Adjustment: added "and the same figure is what the monthly cap is measured against" so §3.8's later cap sentence ("the partner's `purchased_points_mtd` plus `points_quantity`") cannot be read against a different, SETTLED-only quantity — the impl gate and the stored counter are the same expression.

**Orchestrator independent verification:** `PRD_FINALIZED.md` exists, is 466 lines / 115,231 bytes, is NOT byte-identical to `PRD.md` (69 differing wrapped lines), and terminates on the same `ERR_FUND_IMPAIRED_PEAK_BLOCKED` error-table row — so the finalizer genuinely edited in place without truncating.

## Step 9: Complete PRD — 2026-09-04T05:22:00.000Z

**Orchestrator decision (recorded per the autonomy requirement).** Step 9 was run as **three sequential, file-partitioned passes** over the single output document rather than one subagent scan. Rationale: `implementation/` is 3482 lines across 17 modules; a single-pass whole-impl scan reliably under-scans and can return a `PRD_COMPLETED.md` byte-identical to its source (the tell that the walk never happened). Partitioning by implementation file guarantees every module is actually walked, and running the passes sequentially (never concurrently) avoids lost-update collisions on the shared output file. Each pass was told to edit only with `Edit`, never `Write`, so no pass could truncate its predecessors' work. Partition: **A** = routes/hotels.py, routes/members.py, routes/stays.py, middleware.py · **B** = routes/redemptions.py, routes/points.py, routes/complaints.py · **C** = app.py, db.py, errors.py, response.py, support.py, validate.py, services/calc.py, services/derive.py. Pass A also owned Step 0 (`cp PRD_FINALIZED.md PRD_COMPLETED.md`).

### Pass A — routes/hotels.py, routes/members.py, routes/stays.py, middleware.py

`PRD_COMPLETED.md` created by `cp` from `PRD_FINALIZED.md`, then edited only with Edit. 466 lines / 115,231 chars → 467 lines / 119,241 chars (+1 line = the new §5 `ERR_NOT_FOUND` row; +4,010 chars). **16 ambiguity-pins, 12 mismatch-revisions (28 changes).**

- §2.1 — insert — ambiguity — blank/whitespace-only header counts as absent; both header values trimmed before use — `middleware.py:42-49`
- §2.1 — revise — mismatch — owner indirect-ownership list extended with award price window and elite benefit obligation — `hotels.py:287`, `stays.py:280`
- §2.1 — revise — mismatch — member indirect-ownership list extended with elite benefit obligation — `stays.py:281`
- §2.3 — insert — ambiguity — `created_at` ties broken by insertion order (logical clock stamps one instant per request) — `db.py:214-219`
- §2.3 — insert — ambiguity — collections silently narrowed to an owner-bound caller's own rows (excluded from `data` and `total_count`); a foreign `hotel_id`/`member_id` filter is `ERR_FORBIDDEN_RESOURCE_OWNER` — `middleware.py:72-87`, `hotels.py:236`, `stays.py:88-93`, `members.py:107-113`
- §2.6 step 5 — insert — ambiguity — unresolvable `entryId` yields generic `ERR_NOT_FOUND` (404) — `members.py:97` → `validate.py:283-287`
- §2.6 step 5 — insert — ambiguity — required body FK absent/non-string is `ERR_INVALID_REQUEST`, not that entity's 404 — `stays.py:28` → `validate.py:45-56`
- §5 table — insert — ambiguity — added `| ERR_NOT_FOUND | 404 |` row after `ERR_PRICING_ROW_NOT_FOUND` — `errors.py:82`
- §3.1 — insert — ambiguity — termination-cancelled bookings keep `cancel_reason` null — `hotels.py:171`
- §3.2 — insert — mismatch — award price publication enforces none of the stated minimums and reads no property status — `hotels.py:244-264`
- §3.2 — insert — ambiguity — blackout pair ordering breaks a `created_at` tie by insertion order — `hotels.py:351-352`
- §3.3 — revise — ambiguity — duplicate email / missing at-sign both `ERR_INVALID_REQUEST` (400); email compared exactly, no case folding — `members.py:23-28`
- §3.3 — insert — ambiguity — stay-capture body FKs resolved `hotel_id` → `rate_plan_id` → `member_id` — `stays.py:28-32`
- §3.3 — insert — ambiguity — obligations synthesised in fixed order UPGRADE, BREAKFAST, LATE_CHECKOUT — `stays.py:139` → `derive.py:354`, `calc.py:67-72`
- §3.4 — revise — mismatch — `ADJUSTED` is terminal only for the correction loop; a void may still follow — `stays.py:230`
- §3.4 — insert — ambiguity — `bonus_multiplier_applied` recorded 0.00 when the recomputed base is 0; adjustment neither re-synthesises nor waives obligations even if the tier falls — `stays.py:198-199`, `stays.py:201-221`
- §3.4 — revise — mismatch — `ADJUSTED` added to the void's valid origins — `stays.py:230-231`
- §3.4 — insert — ambiguity — a void examines no property status (works at a `TERMINATED` property) — `stays.py:224-231`
- §3.4 hop two — insert — ambiguity — stay retains `program_fee_assessed_cents`, `base_points_awarded`, `bonus_points_awarded`; the credit is the status-filter exclusion alone — `stays.py:237-242`, `derive.py:250-256`
- §3.4 hop four — revise — mismatch — waive sweep runs against the recomputed tier whether or not it fell, so an obligation from a higher `tier_at_checkin` is waived too — `stays.py:248` → `derive.py:332-348`
- §3.4 — revise — mismatch — voiding from `DISPUTED` **or** `ADJUSTED`; the sweep reverses every entry naming the stay, adjustment deltas included — `stays.py:242` → `derive.py:114-140`
- §3.8 — insert — ambiguity — point-adjustment answers HTTP 201 — `members.py:87`
- §3.8 — insert — ambiguity — a clawback may drive `point_balance` below zero; no floor — `members.py:69-87`
- §4 POST /loyalty/hotels — revise — mismatch — dropped "region" (no such field) — `hotels.py:45-62`
- §4 GET /loyalty/hotels — revise — mismatch — filters are status and market tier only — `hotels.py:71`
- §4 GET /loyalty/members — revise — mismatch — "enrolment channel" → email address — `members.py:62`
- §4 GET /loyalty/blackout-windows — revise — mismatch — dropped "scope" filter — `hotels.py:403-404`
- §4 GET /loyalty/elite-benefit-deliveries — revise — mismatch — dropped "property, member" filters — `stays.py:293-294`

Deferred to pass C: `db.py` version semantics (one bump per row per request; `apply_derived` writing nothing when no value moves) versus §2.4/§2.9's "recomputing a derived field counts as a mutation".

### Pass B — routes/redemptions.py, routes/points.py, routes/complaints.py

467 lines / 119,241 chars → **467 lines / 122,100 chars** (+2,859 chars; all edits in-paragraph). No line pass A had touched was re-edited (pass A's 22 diff hunks vs pass B's 17 are disjoint, 39 total). **10 ambiguity-pins, 7 mismatch-revisions.**

- §2.5 — insert — ambiguity — `current_utc` is a required string that must parse as an ISO 8601 instant, unparseable values refused with `ERR_INVALID_REQUEST` — points.py:230-234
- §2.6 item 8 — revise — mismatch — quantity-range list omitted the partner minimums and the breakage decimal bound: added `points_cost_per_1000_cents` >= 1, `monthly_cap_points` >= 1000, "at most four decimal places" on `breakage_rate_pct`, and "partner registration" to the guarded-endpoint list — points.py:29-30, points.py:215-216
- §3.6 — insert — ambiguity — booking body FKs resolve `hotel_id` before `member_id` (unknown-both reports `ERR_HOTEL_NOT_FOUND`), `member_id` read first for the ownership check — redemptions.py:64-68
- §3.6 — revise — mismatch — booking creation also recomputes the fund's `outstanding_points` (enumeration previously stopped at `point_liability_cents`) — redemptions.py:146-150
- §3.6 — revise — mismatch — confirm is **not** open to the hosting `HotelOwner` (ADMIN/AGENT/MEMBER only, owner gets `ERR_UNAUTHORIZED`), and the `HELD` status test precedes the property-status test — redemptions.py:184-194
- §3.6 — revise — mismatch — complete-stay checks booking status before the clock-elapse rule — redemptions.py:206-210
- §3.6 — revise — mismatch — no-show checks booking status before the arrival-date rule — redemptions.py:227-231
- §3.7 — insert — ambiguity — `period_month` is exactly seven characters shaped `YYYY-MM` with month 01–12, else `ERR_INVALID_REQUEST` — redemptions.py:278-281
- §3.7 — insert — ambiguity — rejection resets only the six money figures: `released_by_user_id`, `occupancy_pct_at_release`, `adr_cents_at_release` stand, and the property's `reimbursement_owed_cents` is re-derived — redemptions.py:425-436
- §3.8 — insert — ambiguity — partner `name` bounded 1 to 200 characters — points.py:25
- §3.8 — insert — ambiguity — purchase FKs resolve `member_id` then `partner_id`, and partner existence precedes the channel-agreement test (unknown partner on a direct purchase → `ERR_PARTNER_NOT_FOUND`) — points.py:66-83
- §3.8 — revise — mismatch — the two purchase caps are evaluated in §2.6 precedence (partner monthly cap reported ahead of the member annual cap), not in the order the paragraph lists them — points.py:87-93
- §3.8 — revise — mismatch — `adjustment_reason` is populated only on the point-adjustment endpoint's `GOODWILL` entry; the complaint-resolution `GOODWILL` entry carries none — complaints.py:157
- §3.9 — insert — ambiguity — complaint FKs resolve `member_id` then `related_delivery_id`; a `related_delivery_id` supplied with a non-benefit-denial subject is still resolved (`ERR_DELIVERY_NOT_FOUND`) and ownership-checked (`ERR_DELIVERY_MEMBER_MISMATCH`) before being discarded to null — complaints.py:34-57
- §3.9 — insert — ambiguity — provide-info `description` bounded 1 to 2,000 characters — complaints.py:128
- §3.9 — revise — ambiguity — a negative `goodwill_points` takes the `RESOLVED_UPHELD` arm exactly as zero/omitted does — complaints.py:145-163
- §3.9 — insert — ambiguity — `DELIVERY_ORDERED` computes the recovery from ADR/nights as they read at adjudication and leaves `denial_reason` standing rather than clearing it — complaints.py:217-224

### Pass C — app.py, db.py, errors.py, response.py, support.py, validate.py, services/calc.py, services/derive.py

467 lines / 122,100 chars → **470 lines / 127,992 chars**. **11 ambiguity-pins, 2 mismatch-revisions (13 edits).**

- §2.2 — insert — ambiguity — added a bullet pinning the transport-layer failures: unknown path → `ERR_NOT_FOUND` 404, undeclared method → `ERR_METHOD_NOT_ALLOWED` 405, unexpected fault → `ERR_INTERNAL` 500 (only 5xx), trailing slash reaches the same endpoint; noted the first two precede header checks — app.py:49-78, app.py:25
- §5 — insert — mismatch — added the two catalogue rows the table omitted, `ERR_METHOD_NOT_ALLOWED | 405` and `ERR_INTERNAL | 500`, placed after `ERR_NOT_FOUND` so the table still ends on the peak-blocked row — errors.py:83-84
- §2.3 (pagination) — insert — ambiguity — pinned `total_count` as post-filter/post-narrowing and `has_more` as `offset + len(page) < total_count`, so a page past the end reports false — response.py:88-93
- §2.3 (filters) — insert — ambiguity — unrecognised query parameters are ignored, not refused; recognised filters match by exact string equality; a row whose filtered field is null never matches — support.py:9-28
- §2.4 — revise — mismatch — **the deferred item**: re-derivation counts as a mutation *only when a value moves*; at most one version increment per row per request; a row created by the request stays at `version` 1 even if a later step re-derives it — db.py:161-207
- §2.5 — insert — ambiguity — the logical clock also stamps every row's `created_at`/`updated_at` and every envelope's `api_request_timestamp` — db.py:80, response.py:26
- §2.5 — insert — ambiguity — `current_utc` parsing: `Z`/explicit offset converted to UTC, zone-less instant read as UTC, bare `YYYY-MM-DD` accepted as midnight UTC — db.py:88-106
- §2.6 step 5 — revise — mismatch — a required body FK must be a string with at least one non-whitespace character (blank-but-non-empty is 400, not a 404) — validate.py:45-56
- §2.6 step 5 — insert — ambiguity — optional body FKs (`partner_id`, `related_delivery_id`): absent/`null` skipped, supplied-but-blank is `ERR_INVALID_REQUEST`, and a passing FK is resolved untrimmed — validate.py:59-65
- §2.6 step 6 — insert — ambiguity — JSON `null` counts as absent (required → missing, optional → default); strict typing (int fields reject booleans, numeric strings, and fractional/exponent numbers; percentage fields accept int or float only); non-object and unparseable bodies refused here; absent body read as `{}` — validate.py:26-44, 108-144
- §2.6 step 7 — insert — ambiguity — an unparseable/impossible calendar date fails the shape step with `ERR_INVALID_REQUEST` and never reaches the 422 range test — validate.py:147-152
- §2.7 — insert — ambiguity — "half up" means half away from zero, visible only on the two products allowed to go negative (delinquency surcharge on a deficit fee base, valuation of negative outstanding points) — calc.py:145-147, 293, 331
- §2.11 / §3.8 — insert — ambiguity — fund row opens with `created_at`/`updated_at` at the clock epoch and `version` 1 regardless of which endpoint runs first (derive.py:17-34); the 999.0000 sentinel is reserved for a liability of *exactly* zero, so a negative liability or negative cash yields a signed, un-clamped ratio and an `IMPAIRED` posture (calc.py:337-349)

**Deferred item resolution:** implementation is authoritative and §2.4/§2.9 were overstated. `db.touch` is the only version writer and is idempotent per row per request (`_written`, cleared in `before_request`), and `apply_derived` calls it only when at least one derived value actually changes. So: (1) a no-op re-derivation writes nothing — neither `updated_at` nor `version` moves (e.g. the non-qualifying posting arm's `recompute_hotel` leaves the property untouched); (2) a request that both transitions a row and re-derives it, or that reaches it twice through one cascade, yields exactly +1 (posting that moves the fee ledger *and* tips the property into `FEE_DELINQUENT`; batch payment that clears the ledger *and* cures delinquency; termination's `recompute_hotel` + final `touch`); (3) a row created in-request stays at `version` 1 even if later re-derived — the only realised case being the fund on the first request of the process, which keeps `version` 1 even for `/program-fund/revalue`. §2.4 revised to state all three and §2.9's "the resulting write is a mutation" qualified accordingly; §3.8's "explicit revaluation increments the version" left intact since §2.4 now carries the creation-request caveat.

**§5 table verification (pass C):** now matches `errors.py` exactly — 62 ids on both sides, zero status mismatches, no id in one and not the other. The only rows corrected were the two additions above; no existing row's status was wrong.

### Step 9 totals and orchestrator verification

- **Aggregate: 58 changes across the three passes — 37 ambiguity-pins, 21 mismatch-revisions.**
- `PRD.md` 466 lines / 113,377 chars → `PRD_FINALIZED.md` 466 / 115,231 → `PRD_COMPLETED.md` **470 lines / 127,992 chars** (+4 lines, +12,761 chars over the original PRD, +12.9 %).
- Orchestrator verified independently: `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` (so the scan genuinely ran); it terminates on the `ERR_FUND_IMPAIRED_PEAK_BLOCKED` error-table row; all 28 section headers survive; and its §5 table cross-checks against `implementation/errors.py` at 62/62 ids with zero status mismatches and no one-sided ids.
- Also verified that no `.py` file under `workspace/implementation/`, `test_suite/` or `test_helpers/` is newer than `results.1.json` — Steps 8 and 9 touched documentation only, so the Step 7 result (8 rounds × 333/333) still describes the shipped code exactly.

**Pipeline complete.** Step 9 has written `workspace/PRD_COMPLETED.md`.
