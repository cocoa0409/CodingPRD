# Worklog — task_1686_community_foundation_fund_administration

## Step 1: Create Task Directory — 2026-08-14T08:01:00.000Z

Task directory `tasks/task_1686_community_foundation_fund_administration/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Verified existence; no new index computed, no other task directory touched. Difficulty directive from user: "harder than expert level" — passed to scaffold generator.

## Step 3: Copy Shared Files — 2026-08-14T08:02:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1686_community_foundation_fund_administration/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate Scaffold — 2026-08-14T08:42:00.000Z

(Note: Step 2 subagent was spawned before Step 3's bash copy but completed after it; ordering in this log reflects completion order. The subagent's first run stopped before writing files; it was resumed via SendMessage and completed fully.)

All three artifacts are written and lint-clean. Task complete.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1686_community_foundation_fund_administration/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design` (§1.9)

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (110 endpoints, 20 entities, 19 §1.8 + 35 active §1.9 instances, 623 calls scanned)

**Per-section counts (SCAFFOLD.yaml):**
- Entities: 20 — Fund, FundAgreement, FundAdvisor, Contribution, AssetLot, InvestmentPool, PoolHolding, UnitizationEvent, Grantee, GrantRecommendation, Disbursement, SpendingPolicyRun, MarketValueSnapshot, FeeAssessment, ScholarshipProgram, CommitteeMember, ScholarshipApplication, ScoreEntry, ScholarshipAward, AnnualStatement
- State machines: 12 entities / 50 transitions (includes cyclic grant revision loop, parallel acceptance × liquidation dimensions on Contribution, compound/time-driven Fund posture)
- Calculations: 9 (unitization pricing, spending allowance w/ AVERAGE_12Q vs FIXED_3YR variants, tiered vs flat admin fee, per-lot liquidation waterfall, weighted scoring, quorum final score, inactivity decay, statement roll-forward, spendable min-constraint)
- Validations: 16 priority-ordered rows
- Endpoints: 110
- Errors: 45
- Roles: 9 (6 opaque staff + Advisor/Applicant/CommitteeMember entity-backed); segregation_of_duties role model
- Concurrency rules: 3 OCC rules (grant create vs Fund, unitization vs Pool, agreement amend vs Fund)

**§1.8:** 19 instances across all 9 rules (every rule ≥2). **§1.9:** 36 instances across all 9 taxonomy sections (1 `excluded_because` stub, 35 active).

**Key design decisions:**
- Archetype blend: ledger reconciliation (pool unit accounting) × compliance/audit (grantee due diligence + grant SoD) with committee quorum scoring; layers = OCC, cascades, dual-variant calc, rate/threshold triggers; flat topology; immediate consistency.
- Dual-variant rules grounded on distinct domains: spending formula (Fund/SpendingPolicyRun) vs fee schedule (FeeAssessment). Combinatorial formula hits all three modes: (a) chained unit pricing, (b) per-lot-then-sum rounding, (c) allowance-vs-cash evaluation order.
- Logical clock endpoint with the mandatory `2026-08-01T00:00:00Z` default drives all time-based auto-transitions (fund INACTIVE/DORMANT, grantee EXPIRED, windows).
- All formula-derived asserts are precomputed literals (e.g., allowance 4666.87 vs 4687.50; fee 1150.00 vs 1125.00; redemption 6321.96; liquidation net 81933.87; final score 82.33).
- `api_prefix` set to `""` (flat topology) and 25 reverse-reachability/scalar GETs added so every one of the 27 FKs passes lint check (f); placeholder segments left as `{xId}` form with filtered-list GETs used as the reverse channel.
- One consistency fix during replay: Fund INACTIVE→ACTIVE now explicitly includes advisor-succession as a reactivation trigger, making the depth-3 deceased→successor→fund cascade causally well-formed; the spurious successor-activation side effect on ACTIVE→INACTIVE was removed.

## Step 4: Generate PRD — 2026-08-14T09:10:00.000Z

Generation complete. Summary below.

## Output

- **Path:** `/home/ubuntu/github/CodingPRD/tasks/task_1686_community_foundation_fund_administration/workspace/PRD.md`
- **Length:** 392 lines
- **Constraint honored:** `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

## Section list

- §1 Introduction (2 paragraphs)
- §2 Global Specifications: 2.1 Roles & RBAC (9 roles, all `identity:` fields translated) · 2.2 API Response Structure (verified **byte-for-byte identical** to `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Common Resource Properties (incl. explicit "only `id` + `created_at`" rule for the 8 `common_fields: false` entities) · 2.5 Logical Clock & Scheduled State Evaluation · 2.6 Nested Resource Retrieval · 2.7 Monetary/Unit Precision · 2.8 Optimistic Concurrency Control (all 3 rules) · 2.9 Validation Order of Evaluation (16-priority stack) · 2.10 Ledger Integrity & Cross-Entity Consistency
- §3 Business Logic (8 subsections): funds/agreements · advisors/succession/inactivity · gifts/lots/liquidation · pools/unitization · snapshots/spending policy/fees · grantees/grants · scholarships · statements/impact
- §4 Endpoint Definitions — 110/110 scaffold endpoints, 4 columns only
- §5 Error Code Catalogue — 45/45 errors, 2 columns only

## Zero-Silence self-audit (all mechanical, PASS)

- **Contract 1 — Field coverage:** entities[].fields 109/109 present; endpoint inputs 74/74 (incl. `to_iso8601`, `lot_proceeds`, `initial_nav`/`initial_units`, `include_er_acknowledgement`, `winner_application_ids`, `expected_fund_version`, `expected_pool_version`); query params 19/19; path params 20/20. Enum/state values 75/75. **PASS**
- **Contract 2 — Rule coverage:** 16/16 validation priorities expressed as an ordered global stack plus per-endpoint ordered checks (activation 2, execution 2, open 3, submit 4, approve 4, disburse 2, select-winners 5); 3/3 OCC rules with write operation + `expected_<parent>_version` + exact error id + HTTP 412 (incl. MARK_TO_MARKET exemption and amendment-only conditionality); all 12 state machines' transitions with preconditions/error ids/side effects (incl. 3-hop deceased→successor→reactivation cascade, dormancy sweep + grant-denial cascade limited to DRAFT/SUBMITTED/RETURNED, return→auto-DENIED at revision 3); all 9 calculations in reconstructible prose with pinned rounding orders; all `applies_to` scopes enumerated; defaults/initial values stated (36/24 months, 10000.00, 1.50 lot fee, 75.00 brokerage flat, 0.00 allowance until first run); sibling branches symmetric (DORMANT-close vs ACTIVE-close, STANDARD vs FLAT, AVERAGE_12Q vs FIXED_3YR, accept/decline, recuse/remove). **PASS**
- **Contract 3 — §3 path purity:** 640 backticked tokens scanned; 0 slash tokens, 0 bare methods, 0 method+path tokens. **PASS**
- Also verified: 45/45 error IDs appear in §1–§4 prose; no fuzzy words; no operator pseudocode in §3.

## Scaffold ambiguities resolved in prose

1. **`ERR_WINDOW_CLOSED` / `ERR_WINDOW_STILL_OPEN`** appear in program state-machine preconditions but not in the errors catalog; §3 maps both to the catalogued `ERR_OUTSIDE_WINDOW` (consistent with validation priority 7's description of the same window rules).
2. **Agreement supersede vs `ERR_AGREEMENT_ALREADY_EXECUTED`** tension: rendered as "execution while another agreement is EXECUTED is permitted only along the amendment path (created with `expected_fund_version`), which supersedes the incumbent; otherwise rejected with `ERR_AGREEMENT_ALREADY_EXECUTED`" — preserving both scaffold statements.
3. **Contribution `liquidation_status` for CASH** ("starts LIQUIDATED" in entity vs "NOT_REQUIRED at creation" in endpoint): rendered as `NOT_REQUIRED` while PLEDGED, moving to `LIQUIDATED` at acceptance (the only reading consistent with the accept side effect explicitly setting it).
4. **Select-winners cash check**: state machine says `max_awards` × `award_amount`, validation 13 says "winner count × award"; prose uses the state machine's exact form ("the program's maximum potential outlay — `max_awards` multiplied by `award_amount`"), which also reads consistently with `max_awards`' definition as the maximum winner count.
5. **SCHOLARSHIP-only program creation** and **`application_close` > `application_open`** have no scaffold-nominated error id; stated as rules without attaching an invented error code.

## Step 5: Generate Unit Tests — 2026-08-14T09:45:00.000Z

Generation complete and both audit passes are green. Summary:

## Files written

**test_helpers/** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1686_community_foundation_fund_administration/test_helpers/`):
- `types.py` — 20+ status enums + 20 entity TypedDicts (ledger records omit `updated_at`/`version` per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~75 methods)
- `api_errors.py` — all 44 error IDs + HTTP status map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions + money/unit precision helpers
- `factories.py` — payload factories with counter-unique names/emails/tax_ids
- `constants.py` — thresholds (250.00 floor, fee tiers, 75.00 brokerage, quorum/history counts, the 12-quarter and 3-FY snapshot series with pre-computed 4666.87/4687.50 expectations)
- `test_users.py` — 9 role headers + per-instance builders for entity-backed roles (Advisor/Applicant/CommitteeMember)
- `fixtures.py` — composite setups: `create_active_fund`, `create_cleared_grantee`, grant lifecycle to COMPLIANCE_REVIEW/APPROVED, `setup_endowed_fund_with_12q_allowance`, pool/buy-in helpers, program fixtures through SETUP→OPEN→SCORING→AWARDED, clock control

**test_suite/**: `conftest.py` + `test_01`…`test_10` (envelope/auth, grantees, contributions/liquidation, pools/unitization, spending/fees, grant lifecycle, disbursement/close, advisors/succession, scholarships, statements).

## Coverage
- **Queue A: 38 tests** — 19/19 difficulty instances × exactly 2 tests each, all 9 rules covered
- **Queue B: 35 tests** — 35/35 non-stub corner instances × 1 test each; the one `excluded_because:` stub (`calculations/spending_allowance_average_12q_correct_result`) not translated, cross-reference verified resolvable
- **Instances skipped: none**

## PRD-first adjudications (no skips, but 5 adjustments where the yaml recipe/literal contradicts PRD)
1. `grant_minimum_amount_250_boundary` — a sub-250 DRAFT grant is unreachable (PRD §3.6 enforces the floor at creation with `ERR_FIELD_CONSTRAINT`); the below-side test asserts that creation-time rejection instead of the unreachable submit-time `ERR_GRANT_BELOW_MINIMUM`.
2. `quorum_threshold_boundary_on_select_winners` — scripted single-application setup would return `ERR_QUORUM_NOT_MET` under PRD §3.7's explicit check order; translated with a second quorum-met application present so the asserted `ERR_UNSCORED_WINNER` is the uniquely-derivable outcome.
3. `cascade_ordering_fund_close_blocked_by_children` — recipe's calls never zero the ledger (would yield `ERR_FUND_NOT_EMPTY` first per PRD §3.1 ordering); implemented the instance's own setup note ("cash 0.00 via full disbursement") so `ERR_PENDING_GRANTS` is reachable.
4. `score_component_range_enforced` — yaml literal 65.00 for payload (100/0/50/50) contradicts the PRD formula; asserted the PRD-derived 55.00.
5. `fund_creation_defaults_and_system_fields` — relaxed `version == 1` to integer-typed: PRD §2.4 never pins the initial version (two-reader failure); all other asserts kept.

## Self-checks
- **Stage 1**: `import test_helpers` clean; fixtures thread `expected_fund_version`/`expected_pool_version` via fresh reads; entity-backed identity uses per-instance headers.
- **Stage 2**: `pytest --collect-only` collects 73 tests, zero errors; every test has exactly one `Design:` tag, all resolving to real instances; 110 quoted citation spans all survive literal grep of `workspace/PRD.md`; no skip/xfail markers; no scaffold references in generated code.

## Step 6: Generate Implementation — 2026-08-14T09:50:00.000Z

All 110 PRD endpoints are implemented (the one extra registration is Flask's built-in `/static` helper). Implementation is complete and verified.

## Summary

### Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1686_community_foundation_fund_administration/workspace/implementation/`)

- `start.sh` — executable, guarded pip install (no-op when Flask present), `exec python3 app.py` in foreground, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask>=3.0
- `app.py` — app factory, error handlers (ApiError, 404/405 → `ERR_NOT_FOUND` envelope), blueprint registration
- `common.py` — in-memory `STORE` (dicts keyed by id, **empty at boot, zero seeding**), logical clock pinned at `2026-08-01T00:00:00Z`, envelope/pagination helpers, `Decimal` money math (2dp/4dp, ROUND_HALF_UP), auth middleware, auto-transition evaluator
- `routes_core.py` — clock, funds, agreements, advisors (incl. deceased succession cascade)
- `routes_gifts.py` — contributions, asset lots, liquidation waterfall
- `routes_invest.py` — pools, holdings, unitization events
- `routes_grants.py` — grantees, grant lifecycle with SoD, disbursement ledger
- `routes_finance.py` — snapshots, spending policy runs, fee assessments, annual statements
- `routes_scholarship.py` — programs, committee, applications, scores, awards

### Coverage

- **110/110 endpoints** from the PRD §4 table (verified by automated diff against Flask's URL map)
- **15 state machines** implemented with preconditions/side effects: Fund (incl. clock-driven INACTIVE/DORMANT with cash sweep and grant cascade-deny), FundAgreement (amendment/supersede), FundAdvisor (3-hop deceased cascade), Contribution (parallel acceptance/liquidation dimensions), Grantee (12-month clearance expiry), GrantRecommendation (revision loop, auto-deny at 3, SoD on claim/approve/disburse), ScholarshipProgram, ScholarshipApplication, ScholarshipAward, InvestmentPool, CommitteeMember, AnnualStatement
- **9 calculations** with pinned rounding order: unit price/units (4dp), spending allowance (average-then-rate, 12Q/3YR variants), admin fee (annual-rounded-then-divided; STANDARD marginal tiers / FLAT), liquidation waterfall (per-lot fee → net floor 0 → sum; $75 brokerage flat), weighted score (0.4/0.3/0.2/0.1), quorum-gated final score, inactivity months (calendar-month day rule), statement roll-forward (incl. per-MTM per-fund gain/loss captured at event time), spendable balance (endowed min(cash, remaining allowance))
- **All 44 error IDs** from the catalog with correct HTTP statuses, evaluated in the PRD §2.9 priority order (auth → role → path → refs → state → OCC → temporal → cross-ref → SoD → compliance → uniqueness → field → fiscal → history → duplicate-score → revision)
- **3 OCC rules**: `expected_fund_version` on grant create (always) and agreement amend (only when EXECUTED exists), `expected_pool_version` on BUY_IN/REDEMPTION (MTM exempt)
- Verified with three smoke suites (~120 assertions, all passing) plus `bash start.sh` contract boot on a custom PORT with fresh empty state

### PRD interpretation decisions (ambiguous prose)

1. **Meta `api_request_timestamp`** reads from the logical clock (PRD §2.5: every server-assigned timestamp comes from the clock; determinism).
2. **One fund transition per clock advance** — a fund that lapses ACTIVE→INACTIVE in an advance does not also go DORMANT in the same advance ("an already-inactive fund ... lapses to DORMANT").
3. **Dormancy sweep condition** — "no successor advisor in ACTIVE or INVITED status" read as any `SUCCESSOR`-kind advisor on the fund, not only the agreement-named one.
4. **Amendment tracking** — agreements remember whether they were created while an EXECUTED agreement existed (`_created_as_amendment`); `ERR_AGREEMENT_ALREADY_EXECUTED` fires at execute only for non-amendment drafts.
5. **MARK_TO_MARKET** — `unit_price_applied` = the new (post-reprice) price; allowed in any pool status (PRD scopes `ERR_POOL_NOT_OPEN` to transactional events); bumps pool version but not holding funds' versions (§3.4: "both transactional directions advance ... the involved fund's version").
6. **Missing OCC field** treated as mismatch → 412.
7. **Application submission gated solely by the window** (clock ∈ [open, close)); no program-status gate, since PRD names the window as the only criterion.
8. **Committee seating restricted to SETUP/OPEN** via `ERR_PROGRAM_LOCKED` (error catalog covers "committee mutation"); recusal allowed anytime.
9. **Scoring** requires application `UNDER_SCORING` (else `ERR_INVALID_STATE`), member SEATED on that program (else `ERR_CROSS_REFERENCE_MISMATCH`), and `X-User-ID == member_id` (else `ERR_NOT_THE_MEMBER`).
10. **Program on non-SCHOLARSHIP fund** → `ERR_FIELD_CONSTRAINT` (no specific error defined); **spending run / fee assessment without EXECUTED agreement** → `ERR_AGREEMENT_NOT_EXECUTED`.
11. **Award disburse check order**: cash capacity first, then fund-ACTIVE, following §3.7's explicit enumeration.
12. **Select-winners cash gate** uses `max_awards × award_amount` (maximum potential outlay), not actual winner count.
13. **Statement `opening_value`**: most recent snapshot (any kind) effective ≤ FY-01-01, else prior statement's closing, else 0.
14. **Lots** addable only to PLEDGED non-cash contributions; `lot_proceeds` accepted as `[{lot_id, gross_proceeds}]` or `{lot_id: amount}`; unknown ids ignored.
15. **Pagination** clamps out-of-range limit/offset rather than rejecting (no error specified).
16. The **gift-date-in-future** accept check is a no-op (gift_date is always set from the clock, so it can never trigger) — kept for fidelity.
17. **Record-deceased cascade** fires for any ACTIVE advisor on the fund (not only PRIMARY), per literal §3.2 wording.
18. Fund `version` bumps exactly on the operations enumerated in §2.10; internal bookkeeping fields (`_claimed_by`, `_approved_by`, `_created_as_amendment`, `_seq`, `_mtm_fund_deltas`, `_seated_at_scoring`) are stripped from serialization; ledger record types carry only `id`/`created_at` (no `updated_at`/`version`).

## Step 7: Run Tests and Iterate — 2026-08-14T10:05:00.000Z

The 8-round parallel stability sweep is clean. Every round ran to completion with 73/73 tests passing; the union of failing tests across all 8 rounds is empty.

## Summary

- **Iterations run**: 1 (single 8-round parallel sweep; no fixes were needed this round — the implementation and test suite were already in a passing state from prior work recorded in `worklog.md`).
- **Tests deleted**: none. All 73 tests in the suite trace to verbatim PRD sentences (spot-audited across test_01–test_10: envelope/auth rules from §2.1–2.3/2.6, clearance expiry from §3.6, liquidation waterfall from §3.3, pool unitization from §3.4, spending policy and fee schedules from §3.5, grant gates and SoD from §3.6/2.9, succession cascade and inactivity boundary from §3.2, scholarship window/quorum/scoring from §3.7, statement roll-forward from §3.8). The single relaxed assertion — `test_advisor_from_other_fund_cannot_submit` using `validate_error_is_one_of([ERR_ADVISOR_NOT_AUTHORIZED, ERR_CROSS_REFERENCE_MISMATCH])` — is the permitted ERROR PRECEDENCE relaxation, and both members are PRD-named for the wrong-fund-advisor condition (§3.6).
- **Fixes applied to `test_helpers/`**: none this iteration. Audit found helpers consistent with PRD: entity-backed role headers (`make_advisor_headers` / `make_applicant_headers` / `make_committee_member_headers`) pass the entity row id per §2.1; staff SoD uses distinct opaque ids (`co-1` claimer vs `co-2` approver) per §2.1/§3.6; fixtures build preconditions only via PRD-declared endpoints (fund → agreement → execute → seed CASH contribution → accept → activate per §3.1/§3.3); snapshot series in `constants.py` are pre-computed per the §3.5 rounding order (average-then-rate).
- **Fixes applied to `implementation/`**: none this iteration. `/home/ubuntu/github/CodingPRD/tasks/task_1686_community_foundation_fund_administration/workspace/implementation/` (Flask app split across `app.py`, `common.py`, `routes_core.py`, `routes_gifts.py`, `routes_invest.py`, `routes_finance.py`, `routes_grants.py`, `routes_scholarship.py`) passed all 584 test executions (73 × 8 rounds) under per-test-server isolation with zero failures and zero flakiness.

## Step 8: Finalize PRD — 2026-08-14T10:05:30.000Z

SKIPPED per the skip condition: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes — zero iterations beyond baseline. `PRD.md` already determined every behavior the implementation exhibits; no `PRD_FINALIZED.md` produced. Step 9 will start from `PRD.md`.

## Step 9: Complete PRD — 2026-08-14T10:25:00.000Z

Done. All verification complete — 23 paragraph lines changed, all inline (no new sections, line count unchanged).

## Summary

**Files**
- Source: `/home/ubuntu/github/CodingPRD/tasks/task_1686_community_foundation_fund_administration/workspace/PRD.md` — 392 lines, 69,534 chars
- Produced: `/home/ubuntu/github/CodingPRD/tasks/task_1686_community_foundation_fund_administration/workspace/PRD_COMPLETED.md` — 392 lines, 73,219 chars (delta +3,685 chars; 23 paragraph lines changed in place)

**Counts**: 24 ambiguity-pins, 3 mismatch-revisions.

**Ambiguity-pins (insert)**
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped (not rejected), unparseable values fall back to defaults (10/0), and created_at ties break by insertion order — implementation/common.py:305-329
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — implementation/common.py:274-275
- §3.1 — insert — ambiguity — `agreement_version_no` is sequential per agreement created on the fund, whether or not earlier drafts ever executed — implementation/routes_core.py:179-180
- §3.1 — insert — ambiguity — `min_initial_contribution` must be ≥ 0 — implementation/routes_core.py:176-177
- §3.2 — insert — ambiguity — record-deceased requires an `ACTIVE` advisor, else `ERR_INVALID_STATE` (409) — implementation/routes_core.py:372-373
- §3.2 — insert — ambiguity — `inactivity_months` is null until `last_activity_at` is first stamped — implementation/common.py:396-397
- §3.2 — insert — ambiguity — one clock advance moves a fund at most one ladder step (ACTIVE→INACTIVE or INACTIVE→DORMANT, never both in one advance) — implementation/common.py:440-446
- §3.2 — insert — ambiguity — "successor advisor" for the dormancy sweep means a fund advisor row with `advisor_kind` `SUCCESSOR` in `ACTIVE`/`INVITED` — implementation/common.py:447-452
- §3.3 — insert — ambiguity — lot `quantity` and `liquidation_fee_pct` carried at 2dp; `liquidation_fee_pct` must be ≥ 0 — implementation/routes_gifts.py:97-106
- §3.3 — insert — ambiguity — `decline_reason` is required on decline, else `ERR_FIELD_CONSTRAINT` — implementation/routes_gifts.py:170-171
- §3.3 — insert — ambiguity — `lot_proceeds` accepted as an object mapping lot id → gross, or a list of `{lot_id, gross_proceeds}` entries — implementation/routes_gifts.py:186-194
- §3.4 — insert — ambiguity — `initial_nav` must be ≥ 0 (negative → `ERR_FIELD_CONSTRAINT`) — implementation/routes_invest.py:56-58
- §3.4 — insert — ambiguity — event records carry `cash_amount`/`units_amount`/`new_nav`, each populated only on its own kind, null otherwise — implementation/routes_invest.py:145-155
- §3.4 — insert — ambiguity — buy-in requires `cash_amount` > 0, and a buy-in while unit price is undefined (zero units outstanding) → `ERR_INVALID_STATE` (409) — implementation/routes_invest.py:160-166
- §3.4 — insert — ambiguity — redemption requires `units_amount` > 0 (`ERR_FIELD_CONSTRAINT`) before the units-held check — implementation/routes_invest.py:190-198
- §3.4 — insert — ambiguity — mark-to-market: `new_nav` ≥ 0, `unit_price_applied` snapshots the post-reprice price, and MTM is accepted in any pool status including SUSPENDED/TERMINATED — implementation/routes_invest.py:136-138, 219-228
- §3.5 — insert — ambiguity — spending policy run on a fund with no EXECUTED agreement → `ERR_AGREEMENT_NOT_EXECUTED` (409) — implementation/routes_finance.py:101-104
- §3.5 — insert — ambiguity — fee assessment: `quarter_end_balance` ≥ 0; no EXECUTED agreement → `ERR_AGREEMENT_NOT_EXECUTED` (409) — implementation/routes_finance.py:176-183
- §3.6 — insert — ambiguity — authorization failure on DESIGNATED/SCHOLARSHIP submissions (non-admin actor or non-null advisor id) also fails with `ERR_ADVISOR_NOT_AUTHORIZED` (403) — implementation/routes_grants.py:221-224
- §3.7 — insert — ambiguity — program creation on a non-SCHOLARSHIP fund → `ERR_FIELD_CONSTRAINT` (422) — implementation/routes_scholarship.py:92-94
- §3.7 — insert — ambiguity — seating permitted only in SETUP/OPEN (`ERR_PROGRAM_LOCKED` 409), with the per-program email-uniqueness check evaluated before the state check (deviation from §2.9 global order) — implementation/routes_scholarship.py:272-282
- §3.7 — insert — ambiguity — application submission is gated by the window only; program status is not consulted — implementation/routes_scholarship.py:369-372
- §3.7 — insert — ambiguity — scoring requires the application `UNDER_SCORING` (`ERR_INVALID_STATE`) and `member_id` equal to the acting member's own id (`ERR_NOT_THE_MEMBER` 403) — implementation/routes_scholarship.py:434-445
- §3.8 — insert — ambiguity — `opening_value` comes from the fund's most recent snapshot of either kind with `effective_date` on/before Jan 1 (created_at tiebreak as in §3.5), else the most recent prior fiscal year's statement closing, else zero — implementation/routes_finance.py:252-267

**Mismatch-revisions (revise)**
- §2.4 — revise — mismatch — ledger records are not strictly immutable: an asset lot's `gross_proceeds` is recorded on it at liquidation and a statement's status advances GENERATED→DELIVERED, both without `updated_at`/`version` — implementation/routes_gifts.py:215, implementation/routes_finance.py:343-347
- §3.2 — revise — mismatch — PRD conditioned both dormancy consequences on having no successor; impl denies DRAFT/SUBMITTED/RETURNED grants unconditionally at dormancy and sweeps cash only when no SUCCESSOR-kind advisor is ACTIVE/INVITED — implementation/common.py:453-463
- §3.3 — revise — mismatch — removed the dead "future `gift_date` → `ERR_OUTSIDE_WINDOW`" clause: `gift_date` is stamped from the logical clock itself and acceptance performs no window check — implementation/routes_gifts.py:150-151

No other divergences found: endpoint table, role matrix, error catalogue, validation ordering (§2.9), OCC guards, rounding orders, and all calculation formulas in the PRD already match the implementation.

