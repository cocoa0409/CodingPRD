# Worklog — task_1117_auto_repossession_collateral_liquidation

## Step 1: Create Task Directory — 2026-08-10T17:56:00.000Z

Task directory `tasks/task_1117_auto_repossession_collateral_liquidation/` and its `workspace/` subdirectory were pre-assigned and already exist. Step 1 treated as done (no auto-index scan run).

## Step 2: Generate Scaffold — 2026-08-10T17:56:00.000Z

Scaffold generation complete. All three artifacts written and lint-clean.

## Summary

**Domain design** (compliance-audit archetype with ledger-reconciliation secondary, segregation-of-duties role model, flat topology): RecoveryCase is the central aggregate driving a 16-state branching pipeline (OPENED → CURE_PENDING → CURE_EXPIRED → REPO_ACTIVE → COLLATERAL_SECURED → REDEMPTION_OPEN → CONSIGNMENT_PENDING → IN_AUCTION → SALE_CONFIRMED → DEFICIENCY_NOTICED → CLOSED, plus a COMPLAINT_REVIEW freeze cycle with pre_complaint_state restore and a RESTITUTION unwind path). A fixed logical clock (default `2026-05-01T00:00:00Z`) drives all statutory windows; all automatic transitions fire atomically on clock-set.

**Counts:**
- Entities: 14 (Borrower, LoanAccount, RecoveryCase, CureNotice, RepoAgent, RepoAssignment, PersonalPropertyItem, RedemptionQuote, AuctionHouse, Consignment, SaleRecord, DeficiencyNotice, Complaint, RecoveryLedgerEntry)
- State machines: 10 (incl. cycles on Consignment LISTED→UNSOLD→LISTED, DeficiencyNotice SENT→DISPUTED→SENT, RecoveryCase complaint-review reversion)
- Calculations: 8 (cure amount, redemption/reinstatement quotes with pinned per-diem rounding order, nested min/max reserve pricing, per-line-rounded net proceeds, PROVISIONAL-vs-FINAL deficiency waterfall, LIFETIME-vs-ROLLING_90D agent score, deterministic agent auto-select, shared cost aggregation)
- Endpoints: 58 (incl. `POST /_clock/set_current_utc` test-driving endpoint)
- Validations: 27 rows across 10 priority tiers; Errors: 27 (all triggerable, all covered by a design instance); Roles: 5; OCC concurrency rules: 2
- §1.8 instances: 18 (9 rules × 2, all differentiators satisfied — different entity domains, modes, pairs, metrics, semantics, conserved quantities)
- §1.9 instances: 49 active + 6 excluded_because stubs, spanning all nine claim-extraction sections

**Key findings from the generation-time audit** (fixed before delivery): a dead `ERR_CURE_WINDOW_EXPIRED` (eager clock-set expiry makes the lazy temporal check unreachable — removed and the boundary instance re-pinned to the state error); `ERR_QUOTE_EXPIRED` reachability preserved by making quote auto-expiry conditional on the case not being complaint-frozen; a double-counted sale-expenses term in the deficiency formula (corrected to net-proceeds formulation; all literals recomputed by executing the formulas — e.g., reserve 1,055,750c, redemption quote 2,127,950c, relist markdown 1,002,963c half-up, FINAL deficiency 1,009,530c vs PROVISIONAL 1,114,792c); a missing FK reverse GET for `Complaint.borrower_id`; and two chain-replay bugs (an assignment that would auto-expire before its capacity test, a clock landing exactly on a deadline).

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (58 endpoints, 14 entities, 18 + 49 instances, 883 calls scanned)

**Files written:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1117_auto_repossession_collateral_liquidation/SCAFFOLD.yaml` — 1231 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_1117_auto_repossession_collateral_liquidation/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 768 lines
- `/home/ubuntu/github/CodingPRD/tasks/task_1117_auto_repossession_collateral_liquidation/SCAFFOLD_CORNER_DESIGN.yaml` — 1125 lines

No sibling task directory was inspected at any point.

## Step 3: Copy Shared Files — 2026-08-10T18:53:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_1117_auto_repossession_collateral_liquidation/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T18:54:00.000Z

All audits pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1117_auto_repossession_collateral_liquidation/workspace/PRD.md`.

## Summary

**PRD line count:** 291 lines.

**Section list:**
- §1 Introduction (2 paragraphs)
- §2 Global Specifications — 2.1 RBAC, 2.2 API Response Structure (verbatim block), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 The Logical Clock and Automatic Transitions, 2.6 Monetary Precision and Rounding, 2.7 Validation Order and Error Precedence, 2.8 OCC on Case Documents, 2.9 Ownership Scopes and Segregation of Duties, 2.10 The Append-Only Recovery Ledger
- §3 Business Logic — 3.1 Onboarding/Default Determination, 3.2 Right-to-Cure, 3.3 Agents & Field Assignments, 3.4 Securing Collateral & Personal Property, 3.5 Redemption & Reinstatement, 3.6 Auction Consignment & Sale Certification, 3.7 Deficiency Notices & Settlement, 3.8 Complaints & Restitution Cascade, 3.9 Case Closure
- §4 Endpoint Definitions (58-row, 4-column table)
- §5 Error Code Catalogue (27-row, 2-column table)

**Coverage-audit verdicts:**

```
Field coverage check:
- entities[].fields: 76 required, 76 present, 0 missing
- endpoints[].request_body/path_params/query_params: 16 required, 16 present, 0 missing
  (incl. endpoint-only names: expected_recovery_case_version, payment_amount_cents,
   adjustment_cents, reason, outcome, to_iso8601, current_utc,
   estimated_deficiency_cents, estimated_surplus_cents, basis, limit, offset)
Status: PASS
```

```
Rule coverage check:
- validations[] priority: full 10-tier cascade expressed in §2.7 with each tier's error ids,
  plus the priority-5 tie-break (path-target state before cross-entity) with the worked
  expired-quote example — 1 ordering block, 1 expressed, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed in §2.8 (both write operations,
  expected_recovery_case_version, ERR_STALE_VERSION/412 named; no race framing), 0 missing
- state_machines[].transitions: 52 checked (incl. 7 complaint-eligible freeze rows and
  3 DISMISSED-restore rows), 52 fully expressed, 0 missing
- calculations[]: 8 checked (cure_amount, redemption_quote_amount, reserve_price,
  net_sale_proceeds, deficiency_balance, agent_performance_score, agent_auto_select,
  recovery_costs_total), 8 fully expressed in precise prose with all constants embedded, 0 missing
- validations[] conditions: 27 checked, 27 matchable to error_id in §2/§3 prose, 0 missing
- endpoints[].side_effects / applies_to: 58 checked, 58 expressed, 0 missing
- entities[].fields[] structured content: defaults, initial states, snapshots-never-recomputed,
  append-only ledger exception (common_fields: false), terminal SUSPENDED, never-decremented
  property_item_count, never-extended redemption_deadline — all reconstructible, 0 missing
- sibling-branch symmetry: REDEMPTION/REINSTATEMENT, LIFETIME/ROLLING_90D, PROVISIONAL/FINAL,
  DISMISSED/UPHELD, explicit/auto assignment — all 5 groups at equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 436
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Mapping decisions of note:**
- §3 organized chronologically along the recovery pipeline (9 subsections) rather than by entity or role; the ledger rules were split — immutability/kinds/recovery-costs total in §2.10 (cross-cutting), manual cost posting woven into §3.3's field-operation narrative.
- The clock endpoint was rendered in §2.5 via capability-description mode (`to_iso8601` / `current_utc` named, no path), including the startup default `2026-05-01T00:00:00Z` and the full dependency-ordered auto-transition list with the COMPLAINT_REVIEW freeze carve-out.
- Unit conversions applied per the skill's scattering guidance: ACCEPT_WINDOW_DAYS rendered as "48 hours", EST_RECOVERY_RATIO as "ninety percent", RELIST_MARKDOWN as "× 0.95, a five-percent markdown", grade multipliers as percentages; thresholds like suspension-below-40 and the 365-day year kept literal.
- The apparent tension between `reverses_entry_id` ("the PAYMENT being reversed") and the cost total subtracting REVERSALs of COST_* entries was transcribed faithfully in both places (§2.10) without merging them into a contradiction.
- One defect found and fixed during audit: `ERR_AGENT_LICENSE_MISMATCH` was initially placed in the tier-8 constraint group; the scaffold puts it at priority 6, so §2.7 now lists it with the business-safety tier.

## Step 5: Generate Unit Tests — 2026-08-10T18:55:00.000Z

Generation complete. All work is under `/home/ubuntu/github/CodingPRD/tasks/task_1117_auto_repossession_collateral_liquidation/`.

## test_helpers/ (9 files)
- `types.py` — 14 entity TypedDicts + 14 status/role enums; `RecoveryLedgerEntry` correctly omits `updated_at`/`version` (append-only per PRD §2.4)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (57 methods)
- `api_errors.py` — `ApiErrorId` (27 errors) + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*` validators, ledger-entry negative-field assertion, `parse_instant` (compares instants, not string formattings)
- `factories.py` — payload factories for every writable endpoint (input fields only)
- `constants.py` — all PRD thresholds (14d cure, 10d redemption, 48h accept, 15d retention, 30d deficiency window, 90d rolling window, 40 suspension threshold, 0.95 markdown, 0.9 recovery ratio, grade multipliers, standard timeline anchors)
- `test_users.py` — shared constants for opaque roles + mandatory `make_*_headers` builders for the three entity-backed roles
- `fixtures.py` — 8-tier composite pipeline (`setup_case_cure_pending` → `…_cure_expired` → `…_collateral_secured` → `…_redemption_open` → `…_consign_pending` → `…_in_auction` → `…_sale_confirmed` → `…_deficiency_noticed`) plus ~25 primitive helpers; OCC versions always re-fetched, never assumed
- `__init__.py` — barrel export

## test_suite/ (conftest.py + 9 files, 83 tests)
| file | tests |
|---|---|
| test_01_onboarding_and_case_register.py | 11 |
| test_02_cure_notices_payments_and_ledger.py | 10 |
| test_03_repo_agents_and_assignments.py | 14 |
| test_04_personal_property.py | 5 |
| test_05_redemption_quotes.py | 9 |
| test_06_auction_and_sale.py | 13 |
| test_07_deficiency_notices.py | 8 |
| test_08_complaints_and_restitution.py | 5 |
| test_09_rbac_and_auth.py | 8 |

## Queue A coverage (Difficulty)
17 of 18 instances translated, each with exactly 2 tests (34 tests). **1 skipped:**
- `cross_entity_state_dependency/assignment_accept_requires_agent_active` — fails unique derivability. The instance asserts `ERR_AGENT_SUSPENDED` when accepting after a manual suspend, but PRD §3.3 states manual suspension "fires that same third link, cancelling the agent's live `ASSIGNED` and `ACCEPTED` assignments," so the assignment stands CANCELLED before the accept; PRD §2.7's fixed cascade ("the first failing check wins") evaluates the state tier (step 5) before agent-suspension (step 6), so a PRD-faithful implementation returns `ERR_INVALID_ASSIGNMENT_STATE`. The asserted outcome is unreachable under PRD rules (both manual and auto-suspension fire the cancellation cascade). No weakened variant emitted; the corner stub `error_agent_suspended_covered` stays untranslated per the stub rule (its cross-reference resolves).

## Queue B coverage (Corner)
49 of 49 non-stub instances translated (1 test each). All 6 `excluded_because:` stubs left untranslated; all 6 cross-references verified to resolve to real queue A instance names.

## Self-audit verdicts
- **Stage 1: PASS** — all files compile; `import test_helpers` clean; framework signatures used verbatim (`validate_error` map lookup confirmed str-enum compatible; `get_success_data` returns `data` payload so list helpers work).
- **Stage 2: PASS** — 83 tests collected by pytest with zero import errors; every docstring ends with exactly one `Design:` line resolving to a real instance (0 tag errors); every test carries a verbatim PRD citation surviving normalized grep against PRD.md (0 failures); 0 coverage shortfalls; no `skip`/`skipif`/`xfail` markers; no scaffold references in generated code; version assertions are relative (no initial-version assumption); list lookups by id/kind instead of index where logical-clock timestamp ties are possible.

## Step 6: Generate Implementation — 2026-08-10T18:55:00.000Z

Done. Implementation is complete, boots cleanly, and passed the smoke test.

## File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_1117_auto_repossession_collateral_liquidation/workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
| `start.sh` | 10 | Foreground launcher; guarded `pip install` (no-op when Flask present); `exec python3 app.py`; reads `$PORT` (default 10000), binds `0.0.0.0` |
| `requirements.txt` | 1 | `flask>=3.0` |
| `app.py` | 44 | App factory, ApiError/404/405/generic handlers (all in the error envelope), main |
| `db.py` | 77 | In-memory store (14 dicts keyed by id), logical clock (starts `2026-05-01T00:00:00Z`), `touch()` (updated_at + version++), insertion seq for stable sort |
| `errors.py` | 38 | `ApiError` + all 27 error-id constants from scaffold §1.6 |
| `response.py` | 47 | Envelope: `meta{api_request_id, api_request_timestamp[, limit, offset, total_count, has_more]}`, `response_type`, `data`; errors carry `error_id`/`message` |
| `middleware.py` | 37 | `X-User-ID`/`X-User-Role` auth (401 → 403 role gate), five declared roles |
| `util.py` | 134 | ISO-8601 parse/format (3 fractional digits), Decimal ROUND_HALF_UP, body schema validation (required/type/enum/unknown-field rejection, positive-amount checks), limit/offset validation (1–100 / ≥0) |
| `serializers.py` | 209 | Per-entity JSON shape; ledger entries omit `updated_at`/`version` per PRD §2.4 |
| `services/calc.py` | 250 | All 8 calculation rules: recovery_costs_total, cure_amount, redemption_quote_amount (pinned per-diem rounding), reserve_price (grade table, floor, relist markdown), net_sale_proceeds (per-line rounding before subtraction), deficiency_balance (PROVISIONAL/FINAL), agent_performance_score (LIFETIME/ROLLING_90D), agent_auto_select (half-open overlap, rolling-desc/created-asc ranking) |
| `services/transitions.py` | 149 | Clock auto-transitions, suspension cascade, ledger append helper, restitution cascade |
| `routes/borrowers.py` 51, `loans.py` 62, `cases.py` 220, `agents.py` 212, `items.py` 143, `quotes.py` 115, `auctions.py` 260, `deficiency.py` 177, `complaints.py` 99, `clock_routes.py` 23, `routes/__init__.py` 10 | — | Endpoint handlers, each enforcing the priority cascade: auth → role → existence(404, left-to-right) → ownership(403) → body(400) → state(409, path-resource state before cross-entity) → safety(403/422) → temporal(422) → constraint(409/422) → fiscal(422) → OCC(412) |

Total: 2357 lines across 21 files. No seeding anywhere — the store starts empty on every boot.

## Endpoint count
58 routes registered (verified by enumerating Flask's url_map) — **exactly matches the 58 endpoints declared in SCAFFOLD.yaml §1.5**, including `POST /_clock/set_current_utc`. No deviations.

## Logical clock & atomic auto-transitions
- The clock is a module-level `datetime` on the store, initialized to exactly `2026-05-01T00:00:00Z`; it never reads wall-clock. All business timestamps (`created_at`, `sent_at`, `collateral_secured_at`, `sold_at`, deadlines) derive from it; only the envelope's `meta.api_request_timestamp` uses wall time.
- `POST /_clock/set_current_utc` (RecoveryManager/ComplianceOfficer only) sets `store.clock` then runs `apply_clock_transitions()` synchronously in the same request, in the PRD §2.5 dependency order: (1) SENT cure notices past `cure_deadline` → EXPIRED, then their CURE_PENDING cases → CURE_EXPIRED; (2) ISSUED quotes past `redemption_deadline` → EXPIRED and REDEMPTION_OPEN cases → CONSIGNMENT_PENDING, but only while the case is REDEMPTION_OPEN (COMPLAINT_REVIEW-frozen cases/quotes untouched); (3) ASSIGNED assignments older than 48h → EXPIRED with score recompute and the suspension cascade (rolling < 40 → SUSPENDED → other live assignments CANCELLED). Each mutated entity gets its own `updated_at` + `version` bump; the restitution and suspension cascades are likewise single-request atomic (all preconditions checked before any commit).

## Smoke test result
- `PORT=18123 bash start.sh` booted and served within ~1s; `kill` of the launcher PID (exec'd python) shut it down; a second boot on `PORT=18124` confirmed empty store (`total_count: 0`) and clock reset to `2026-05-01T00:00:00Z` — clean per-test reboot behavior.
- Probes: unauthenticated GET → 401 `ERR_UNAUTHENTICATED` envelope; borrower create → 201 with logical-clock timestamps and `version: 1`; clock set → `{"current_utc": "2026-05-20T00:00:00.000Z"}`; cure notice on a 2-missed-installment loan → `cure_amount_cents: 102500`, `cure_deadline: 2026-06-03` (= sent_at + 14d), case CURE_PENDING v2; repeat create with stale version → 412 `ERR_STALE_VERSION`; list envelope carries `limit/offset/total_count/has_more`; advancing the clock past the cure deadline → notice EXPIRED, case CURE_EXPIRED v3.

## Judgment calls (spec-silent corners)
- Body-referenced FKs that don't resolve (`borrower_id`, `loan_account_id`, `agent_id`, `auction_house_id`) → 400 `ERR_INVALID_REQUEST` (scaffold scopes 404 to path ids only).
- Deficiency-estimate `basis` string: `"consignment_reserve"` when a consignment exists, else `"grade_adjusted_appraisal"` (PRD requires a descriptive string but doesn't pin values).
- Estimate allowed whenever the case has appraisal data (`condition_grade` set = "after COLLATERAL_SECURED"), else 409 `ERR_INVALID_CASE_STATE`.
- Manual suspend of an already-SUSPENDED agent is an idempotent 200 (no agent-state error id exists in the catalog).
- `report-secured` additionally requires the case to be REPO_ACTIVE (blocks it while a case is frozen in COMPLAINT_REVIEW); `report-sale`/`report-unsold` reject with 409 when a non-VOID SaleRecord already exists (upholding the one-sale-per-consignment invariant).
- Version increments once per mutated entity per request, including cascade targets.
## Step 7: Run Tests and Iterate — 2026-08-10T19:30:00.000Z

All 8 rounds pass 83/83. Clean sweep achieved.

## Summary

**Iterations run:** 2 (iteration 1: 76/83 in all 8 rounds; iteration 2 after fixes: 83/83 × 8 rounds, zero flakiness).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1117_auto_repossession_collateral_liquidation/test_helpers/fixtures.py` — added `_parse_ts`/`_fmt_ts`/`_advance_clock_past` helpers; `setup_case_cure_expired` now advances the clock to `max(clock_to, notice.sent_at + 15d)` and `setup_case_consign_pending` to `max(clock_to, quote.valid_until + 1d)`. Why: the composite fixtures used fixed clock anchors (T_SECURE, T_CONSIGN) assuming a pristine `2026-05-01` clock; when a test ran two pipelines sequentially (test_03's `_setup_agent_with_first_window`, test_06's `_setup_two_listed`/`_setup_two_drafts_same_house`), the second case's cure notice/quote was issued at the already-advanced clock, so the fixed anchor no longer fired the automatic expiry and assignment creation was correctly rejected with `ERR_INVALID_CASE_STATE` ("CURE_PENDING does not permit a repo assignment"). Single-use behavior is unchanged (`max()` returns the original anchor at a pristine clock). This fixed 6 tests: `test_agent_field_window_adjacency_accepted`, `test_agent_field_window_true_overlap_rejected`, `test_bid_exactly_at_reserve_accepted`, `test_bid_one_cent_below_reserve_rejected`, `test_auction_listing_touching_windows_rejected`, `test_auction_listing_strict_gap_accepted`.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1117_auto_repossession_collateral_liquidation/test_suite/test_02_cure_notices_payments_and_ledger.py` — `test_cure_payment_insufficient_in_window` now passes the loan overrides (`monthly_payment_cents=20_000, missed_installments=2, late_fees_cents=3_000, ...`) that produce the asserted `cure_amount_cents == 43_000` per the PRD §3.2 formula (missed × monthly + late fees + recovery costs). Previously it passed only `vin`, so factory defaults yielded 147,000 against an assertion of 43,000 — a fixture-input bug, not an implementation bug (the implementation computed 147,000 correctly per PRD).

**Fixes applied to `implementation/`:** none — the implementation was PRD-faithful in every failure; all 7 failing tests traced to test-side construction bugs (STEP 2 outcomes).

No tests were deleted: every failing test's asserted rule traced verbatim to PRD (§3.2 payment sufficiency, §3.3 half-open field windows, §3.6 reserve boundary and closed-interval listing windows), and unique derivability held in each case.

## Step 8: Finalize PRD — 2026-08-10T19:45:00.000Z

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1117_auto_repossession_collateral_liquidation/workspace/PRD_FINALIZED.md` written as a verbatim copy of PRD.md (verified identical via `diff`). Zero edits — no Step 7 diff item revealed a PRD silence or PRD/impl mismatch.

**Line counts / delta:** PRD.md = 291 lines; PRD_FINALIZED.md = 291 lines; 0% delta.

**Per-diff-item verdicts (zero edits made):**

1. **`test_helpers/fixtures.py` — `_advance_clock_past` in `setup_case_cure_expired` (clock → `max(clock_to, notice.sent_at + 15d)`)** — verdict: pure fixture bug. The fixed anchor `T_SECURE = 2026-05-16` (constants.py:43) was calibrated to a pristine `2026-05-01` clock; sequential pipelines advanced the clock, so a second case's notice carried a later `sent_at` and the anchor never passed `cure_deadline`. Impl paths examined: `implementation/services/transitions.py:30-43` (`_expire_cure_notices`: fires when `now > case["cure_deadline"]`), `implementation/routes/cases.py:148,159` (`sent_at = store.clock`; `cure_deadline = sent_at + 14d` via `calc.CURE_PERIOD_DAYS = 14` at `services/calc.py:9`), `implementation/routes/agents.py:92` (assignment create requires `CURE_EXPIRED`/`REPO_ACTIVE`, else `ERR_INVALID_CASE_STATE`). PRD §2.5, §3.2 ("the case's `cure_deadline` is set to the notice's `sent_at` plus fourteen days"; "the moment the logical clock passes `cure_deadline`, the automatic transition of §2.5 fires") and §3.3 (assignment state guard) pin all of this verbatim.

2. **`test_helpers/fixtures.py` — `_advance_clock_past` in `setup_case_consign_pending` (clock → `max(clock_to, quote.valid_until + 1d)`)** — verdict: pure fixture bug, same shape. Impl paths examined: `implementation/services/transitions.py:46-62` (`_expire_redemption_quotes`: `ISSUED` → `EXPIRED` and `REDEMPTION_OPEN` → `CONSIGNMENT_PENDING` when `now > redemption_deadline`), `implementation/routes/quotes.py:42-44` (`redemption_deadline = issued_at + 10d`; `valid_until = redemption_deadline`). PRD §2.5 and §3.5 ("fixes the case's `redemption_deadline` at the quote's `issued_at` plus ten days"; "`valid_until` set equal to the case's `redemption_deadline`"; "a logical time beyond the `redemption_deadline` expires the `ISSUED` quote") pin all of this verbatim.

3. **`test_suite/test_02...py` — `test_cure_payment_insufficient_in_window` now passes loan overrides yielding `cure_amount_cents == 43_000`** — verdict: pure fixture-input bug. The test previously passed only `vin`, so factory defaults (3 missed × 45,000 + 12,000 late fees = 147,000) were used against an assertion of 43,000 (2 × 20,000 + 3,000 + 0 costs). Impl paths examined: `implementation/services/calc.py:75-78` (`cure_amount_cents = missed_installments × monthly_payment_cents + late_fees_cents + recovery_costs_total`), `implementation/routes/cases.py:182-189` (state guard `CURE_PENDING` → then sufficiency vs. live notice's `cure_amount_cents` → `ERR_PAYMENT_INSUFFICIENT`). PRD §3.2 pins the formula verbatim ("the loan's missed installments multiplied by the monthly payment, plus the unpaid late fees, plus the case's recovery-costs total as defined in §2.10") and the guard cascade ("the case must stand in `CURE_PENDING`... and only then is sufficiency judged"). The implementation computed 147,000 correctly; only the test's inputs were wrong.

No edit search log is required beyond the per-item impl paths above, since zero edits were committed.

## Step 9: Complete PRD — 2026-08-10T20:20:00.000Z

All edits applied cleanly. Final state verified by diff.

## Summary

**Source vs. output:** `PRD_FINALIZED.md` 291 lines / 52,929 chars → `PRD_COMPLETED.md` 294 lines / 55,807 chars (+3 lines, +2,878 chars). 13 edit sites, 22 distinct pins/revisions.

**Counts:** 20 ambiguity-pins, 2 mismatch-revisions.

All seven generation-note judgment calls were verified against the actual code (all accurate) and pinned. Changes:

- §2.2 — insert — ambiguity — unknown path or unsupported method → `ERR_NOT_FOUND` 404; unexpected failure → `ERR_INTERNAL` 500 — app.py:20-36
- §2.3 — insert — ambiguity — non-integer `limit`/`offset`, `limit` outside 1–100, or negative `offset` → `ERR_INVALID_REQUEST` 400 — util.py:114-134
- §2.3 — insert — ambiguity — equal `created_at` ties break by creation (insertion) sequence — db.py:75-77
- §2.3 — insert — ambiguity — filters apply before pagination; `total_count`/`has_more` describe the filtered set — response.py:40-47
- §2.4 — insert — ambiguity — `version` starts at 1 on creation — db.py:51-59
- §2.5 — insert — ambiguity — `to_iso8601` applied verbatim, no monotonicity check — clock_routes.py:13-23
- §2.7 — insert — ambiguity — body-referenced FK misses (`loan_account_id`, `borrower_id`, `agent_id`, `auction_house_id`) → 400 `ERR_INVALID_REQUEST`, not 404 — cases.py:47-50, loans.py:27-29, agents.py:83-87, auctions.py:62-64
- §2.7 — revise — mismatch — "amount fields positive integers" → payment/bid/ledger amounts positive; stored balance/appraisal/fee fields accept zero (impl validates `nonneg_int` for loan, appraisal, fee, item-value fields) — util.py:57-63
- §3.1 — revise — mismatch — "moves the loan from `CURRENT` to `IN_DEFAULT`" → loan set `IN_DEFAULT` unconditionally; the one-open-case rule is the only precondition (reopen path per §3.9) — cases.py:51-77
- §3.1 — insert — ambiguity — unrecognized `status` filter value → `ERR_INVALID_REQUEST` 400 — cases.py:93-94
- §3.2 — insert — ambiguity — cure payment responds 201 carrying the created `PAYMENT` ledger entry — cases.py:198-199
- §3.3 — insert — ambiguity — auto-select ties at equal `created_at` break by registration sequence — calc.py:248-249
- §3.3 — insert — ambiguity — create leaving the case in `REPO_ACTIVE` does not modify the case (no version increment) — agents.py:129-131
- §3.3 — insert — ambiguity — suspending an already-`SUSPENDED` agent is an idempotent 200 no-op — agents.py:54-61
- §3.4 — insert — ambiguity — report-secured additionally requires the case in `REPO_ACTIVE` (`ERR_INVALID_CASE_STATE`), after the assignment-state guard — agents.py:181-184
- §3.4 — insert — ambiguity — item inventory restricted to the agent of the case's `SECURED` assignment (`ERR_FORBIDDEN_OWNERSHIP`) — items.py:43-50
- §3.6 — insert — ambiguity — report-sale/report-unsold against a consignment with an existing non-`VOID` SaleRecord → `ERR_INVALID_CONSIGNMENT_STATE` 409, folded into the state guard — auctions.py:188-190, 217-219
- §3.7 — insert — ambiguity — estimate read before any appraisal on file → `ERR_INVALID_CASE_STATE` 409 — deficiency.py:31-33
- §3.7 — insert — ambiguity — `basis` string values pinned: `consignment_reserve` / `grade_adjusted_appraisal` — calc.py:136-147
- §3.7 — insert — ambiguity — no uniqueness constraint on notices; multiple `DRAFT` notices may coexist — deficiency.py:44-67
- §3.8 — insert — ambiguity — dismissal restores only the case status; a consignment withdrawn at filing stays `WITHDRAWN` — complaints.py:56-63, 90-96
- §5 — insert — ambiguity — `ERR_INTERNAL` | 500 catalogue row — app.py:28-36

Deliberately not pinned (no real multiple-interpretation risk): the §2.7 numbered order vs. path-resolution-before-ownership (ownership of a nonexistent target is unevaluable, impl's 404-first is the only viable reading), `has_more` formula (follows from field semantics), and inverted window start/end (PRD mentions no such rule and impl has none).

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_1117_auto_repossession_collateral_liquidation/workspace/PRD_COMPLETED.md`
