# Worklog — task_2105_mutual_fund_transfer_agency

## Step 1: Create Task Directory — 2026-08-16T03:42:19.847Z

Created `./tasks/task_2105_mutual_fund_transfer_agency/` and `./tasks/task_2105_mutual_fund_transfer_agency/workspace/`. Index 2105 = highest existing (2104) + 1.

## Step 2: Generate Scaffold — 2026-08-16T04:53:47.000Z

Generated all three scaffold artifacts in `/home/ubuntu/github/CodingPRD/tasks/task_2105_mutual_fund_transfer_agency/`, built only from the scenario text and the skill spec (no sibling task was read).

## Files
- `/home/ubuntu/github/CodingPRD/tasks/task_2105_mutual_fund_transfer_agency/SCAFFOLD.yaml` (§1.0–§1.7, 130 KB)
- `/home/ubuntu/github/CodingPRD/tasks/task_2105_mutual_fund_transfer_agency/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8, single top-level key)
- `/home/ubuntu/github/CodingPRD/tasks/task_2105_mutual_fund_transfer_agency/SCAFFOLD_CORNER_DESIGN.yaml` (§1.9, single top-level key)

## Complexity profile
Expert-plus. Primary archetype compliance/audit, secondary ledger reconciliation. Layers: dual-variant calculation, cascading side effects, rate/threshold triggers, derived-field reconciliation, optimistic concurrency. Topology **flat** (prioritized), state-machine shape **parallel**, relationship patterns include **self-referential** (ROA household), role model **segregation_of_duties** (all prioritized/0%-usage picks). `api_prefix: "/"`; logical clock defaults to `2026-08-01T00:00:00Z` (a Saturday, so an unset clock deterministically forward-prices to Mon 2026-08-03).

## Contents
- **13 entities**: Fund, ShareClass, ShareholderAccount, Position, NavRecord, Trade, Distribution, DistributionPayment, SystematicPlan, BlueSkyRegistration, PricingErrorCase, OmnibusReconciliation, ShareLedgerEntry (append-only, `common_fields: false`).
- **9 state machines**: ShareholderAccount; Trade × 2 parallel dimensions (`execution_status` × `settlement_status`); NavRecord (two cycles: FINAL↔UNDER_ERROR_REVIEW, PRELIMINARY↔STALE_REPRICE_REQUIRED); PricingErrorCase (branching immaterial vs material with disjoint effects); Distribution; BlueSkyRegistration (ACTIVE↔EXHAUSTED cycle); SystematicPlan (ACTIVE↔SUSPENDED cycle); OmnibusReconciliation.
- **10 calculations**: forward_pricing_trade_date, roa_household_basis (dual-variant market-value vs historical-cost), purchase_trade_pricing (dual-variant preliminary vs final NAV; tier pinned on gross before load), redemption_proceeds_with_cdsc (nested min/max + free allowance + reinvest exclusion), exchange_settlement_pricing, nav_per_share_strike, pricing_error_materiality (50 bps inclusive), distribution_payment_amounts (rounding order pinned per-payment-then-sum), blue_sky_capacity_ledger, omnibus_break_classification.
- **2 OCC concurrency rules** (412): `plan-create-stale-account` on `POST /systematic-plans`, `pricing-error-case-stale-nav` on `POST /pricing-error-cases` — both genuine CREATE-with-supersede races.
- **29 validations** (priority 10→142), **60 endpoints** (incl. `POST /_clock/set_current_utc`), **46 errors**, **5 roles** (4 opaque + `AccountHolder` = `entity_backed:ShareholderAccount`).

## §1.8 / §1.9 instance counts
- §1.8: 9 rule_ids × **2 instances = 18** (meets every §0.5 minimum, each pair differentiated: different entity domains, different combinatorial modes (b)/(c), different non-linear entities, different cascade triggers, different error-category pairs, different metrics+endpoints, different entity pairs, half-open vs closed interval semantics, shares vs registration-dollar conserved quantities).
- §1.9: **72 instances = 59 active + 13 `excluded_because` stubs**, spanning all nine claim-guide sections.

Every formula-derived assertion was computed in Python and written as a literal (e.g. 3245.909 vs 3212.273 shares for the ROA variant split; 942.06 vs the wrong 942.07 rounding order; 50.00 bps exactly → MATERIAL; restated 1875.622 shares with delta −9.378; CDSC 30.00 on 6000.00 gross).

Self-audit: all `grounds` refs resolve, every error code is referenced by a validation/transition, no forbidden concurrency vocabulary, file split honored.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  §1.5 endpoints declared:    60
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     59
  Calls scanned (§1.8+§1.9):  753
```

## Step 3: Copy Shared Files — 2026-08-16T03:42:36.966Z

Copied `./INSTRUCTION.md` → `./tasks/task_2105_mutual_fund_transfer_agency/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-16T05:19:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2105_mutual_fund_transfer_agency/workspace/PRD.md` — 435 lines, ~13,250 words. `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, and no sibling task directory was read.

## Structure

**§1 Introduction** — 3 paragraphs (regulatory framing, flat-topology/dual-lifecycle design, logical clock + segregation of duties).

**§2 Global Specifications** — 10 domain-derived subsections: 2.1 Desk Roles and Request Authentication · 2.2 API Response Structure (byte-identical copy of `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 The Logical Clock and the Business-Day Calendar · 2.5 Record Identity, Audit Fields and the Share Ledger · 2.6 Precision: Dollars, Shares, Prices and Percentages · 2.7 Order of Rejection (all 30 validation priorities as an explicit ordered ladder with `applies_to` enumerations) · 2.8 Version Gating on Superseding Writes · 2.9 Cascade Discipline and Derived-Field Reconciliation · 2.10 Segregation of Duties and Channel Entitlement.

**§3 Business Logic** — 10 subsections following the operational timeline: reference data → accounts/households → NAV strike → registration capacity + order capture → pricing → settlement/ledger/reversal → distributions → systematic plans → pricing errors → reconciliation.

**§4** 60-row endpoint table (4 columns). **§5** 46-row error table (2 columns). Document ends at §5.

## Coverage

- **13 entities / 127 fields**, 5 roles, 43 state transitions across 8 state machines (ShareholderAccount, Trade×2 parallel dimensions, NavRecord, PricingErrorCase, Distribution, BlueSkyRegistration, SystematicPlan, OmnibusReconciliation), **10 calculations** (all constants embedded in business context: 3-business-day as-of window, 10% CDSC free allowance, 365/730-day aging tiers, 50 bps materiality, 24% backup withholding, $1.00 / 1 bp recon tolerance), **30 validations**, **60 endpoints**, **46 errors**, **2 OCC rules**.
- Pinned rounding orders preserved verbatim in prose (per-payment rounding before summation; ROA tier never re-derived from the net amount; single final rounding of the CDSC product).
- The 5-link reprocessing cascade is written link-by-link with each `restated_share_delta` / counter effect named.

## Hard Contract Reports

```
Field coverage check:
- entities[].fields: 127 required, 127 present, 0 missing
- endpoints[].request_body: 58 required, 58 present, 0 missing
- endpoints[].query_params: 33 required, 33 present, 0 missing
- nested breakpoint_tiers keys (min_qualifying_amount, load_pct): 2 required, 2 present, 0 missing
Status: PASS   (two passes run; second pass required exact standalone backticked tokens, not sub-words)

Rule coverage check:
- validations[] with priority: 30 checked, 30 expressed in prose (§2.7 ordered ladder), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id + 412 all named), 0 missing
- state_machines[].transitions: 43 checked, 43 fully expressed (every from→to pair verified mechanically as an explicit arrow), 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 30 checked, 30 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 60 checked, 60 expressed, 0 missing
- entities[].fields[] structured content: 127 checked, 127 reconstructible from prose (defaults/initial values stated for Position, Trade, PricingErrorCase, Distribution, DistributionPayment, SystematicPlan, BlueSkyRegistration, ShareholderAccount, NavRecord), 0 missing
- sibling-branch symmetry: 6 groups checked (immaterial vs. material case branches; 4 cancel sources; ACTIVE/RESTRICTED→CLOSED; PRELIMINARY vs. FINAL pricing variants; MARKET_VALUE vs. HISTORICAL_COST basis; MONTHLY vs. QUARTERLY cadence), 6 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 1038
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Two judgment calls worth flagging: (1) the scaffold's `fund_family_code` description implies family-keyed load-free exchanges while `exchange_settlement_pricing` keys them on `fund_id` — the formula was treated as authoritative and `fund_family_code` is documented as the family grouping code; (2) systematic withdrawal/exchange plans carry a dollar `amount` but generate share-denominated orders with no conversion formula in the scaffold, so the PRD specifies conversion at the source class's most recent priced NAV (the same price behind `market_value_amount`, which the insufficient-value branch compares against) rounded half-up to 3 decimals.

## Step 5: Generate Unit Tests — 2026-08-16T06:15:00.000Z

Test infrastructure and suite are complete and verified.

## Files written

**`/home/ubuntu/github/CodingPRD/tasks/task_2105_mutual_fund_transfer_agency/test_helpers/`** (2,571 lines)
- `types.py` — 20 status/role enums + 13 entity TypedDicts. `ShareLedgerEntry` carries only `id` + `created_at` (no `updated_at`, no `version`).
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (60 methods incl. `/_clock/set_current_utc`).
- `api_errors.py` — 45-member `ApiErrorId` enum + HTTP status map, registered via `set_error_http_status_map`.
- `assertions.py` — precision helpers (`money`/`shares`/`price`/`pct`), `assert_instant_equals`, per-entity assertions, and domain invariants (`assert_registration_capacity_identity`, `assert_trade_state`, `assert_pricing_fields_cleared`).
- `factories.py`, `constants.py`, `test_users.py` (opaque-role constants + per-user builders incl. `make_account_holder_headers` for the entity-backed `AccountHolder`), `__init__.py` barrel.
- `fixtures.py` (1,192 lines) — primitives plus 25 composite scenario builders (dual-channel household, provisional-pricing, three-holder distribution, five-link cascade, capacity-identity desk, CDSC position, same-fund exchange, omnibus reconciliation desks, pending as-of order, …).

**`/home/ubuntu/github/CodingPRD/tasks/task_2105_mutual_fund_transfer_agency/test_suite/`** (3,786 lines) — `conftest.py` + 12 domain-named test files (`test_01_reference_data_and_accounts.py` … `test_12_rejection_precedence.py`).

## Test counts

- **95 tests total**, all collected cleanly by pytest.
- **Queue A (Difficulty): 37 tests** — all 18 instances covered by ≥2 tests (the materiality-boundary instance has 3).
- **Queue B (Corner): 58 tests** — 58 of 59 non-stub instances covered by exactly 1 test each. All 13 `excluded_because:` stubs verified to cross-reference a real difficulty instance; none translated.

## Skipped instance (1)

`Corner/state_machines/opening_a_second_case_supersedes_the_open_case_on_the_same_nav_record` — **skipped: PRD contradicts the asserted outcome.** The recipe expects HTTP 201 when a second pricing-error case is opened against a record the first case already drove to `UNDER_ERROR_REVIEW`, but PRD §3.9 states verbatim: *"The targeted record must currently be `FINAL`; a case opened against a record in any other state answers `ERR_INVALID_NAV_STATE`."* A PRD-only implementer uniquely derives a 409 rejection, so the instance fails the unique-derivability condition. (The supersede rule is effectively unreachable as the PRD is written — a PRD gap, not a test gap.)

## Assertions dropped for non-derivability (test kept)

- `exchange_between_classes_of_the_same_fund_carries_no_sales_load` — dropped the **target-position `cost_basis_amount == 11000.00`** and **source-position `cost_basis_amount == 49528.80`** assertions. PRD §3.6 describes the exchange settlement's effects (target gains `exchange_target_shares`, `EXCHANGE_IN`/`EXCHANGE_OUT` entries, target registration consumes `gross_proceeds_amount`) but never states that an exchange moves either position's cost basis; §3.2 attributes cost-basis movement only to purchases, reinvestments and redemptions. Two faithful readers would diverge. Every other assertion in that instance is retained.

## Verification performed

- **Citation audit**: 208 PRD citations across 95 docstrings; every one survives a whitespace-normalized literal match against `PRD.md`, and every one is ≥8 words.
- **Tag audit**: every test has exactly one `Design:` line; no untagged, dual-tagged, or dangling-tag tests; no unknown tags.
- **No `pytest.mark.skip` / `skipif` / `xfail`** anywhere.
- `pyflakes` clean (only intentional barrel-export "unused import" notices).
- No file under `workspace/implementation/` was read or written; no sibling task directory was read.

## Step 6: Generate Implementation — 2026-08-16T06:35:00.000Z

The implementation is complete and verified. Summary:

## Files written — `/home/ubuntu/github/CodingPRD/tasks/task_2105_mutual_fund_transfer_agency/workspace/implementation/`

**Launcher / deps:** `start.sh` (guarded `pip install`, `exec python3 app.py`, `0.0.0.0:$PORT` default 10000), `requirements.txt` (flask).

**Core (root):** `app.py` (blueprint registration, error handlers, global request lock, Decimal JSON provider), `db.py` (in-memory dicts + deferred one-bump-per-request version/`updated_at` tracking), `clock.py` (logical clock, default `2026-08-01T00:00:00Z`), `dates.py` (business-day calendar, month arithmetic with day clamping), `money.py` (Decimal/ROUND_HALF_UP helpers), `errors.py` (46-code catalogue → HTTP status), `middleware.py` (`X-User-ID`/`X-User-Role`, 5 roles), `validation.py` (shape/precision/enum/date/pagination guards), `constants.py`, `response.py` (`meta`/`response_type`/`data` envelope), `serializers.py`.

**`routes/`** (11 blueprints + `helpers.py`): clock, funds/share-classes, accounts, positions/ledger, blue-sky, nav-records, trades, distributions, plans, pricing-error-cases, reconciliations.
**`services/`**: `capture.py` (forward pricing + as-of controls + blue-sky reservation), `pricing.py`, `settlement.py`, `household.py` (ROA), `bluesky.py`, `positions.py`, `navs.py`.

## Coverage
- **Endpoints: all 61** — machine-diffed against the PRD §4 table, exact match (paths, methods, and per-endpoint role lists including the "All roles" vs. restricted variants).
- **State machines:** ShareholderAccount (4 states + plan cascades), Trade's two independent dimensions (execution × settlement, incl. `RESTATED`, provisional→received fallback), NavRecord (5 states incl. repost cycles), PricingErrorCase (fork + supersede), Distribution (record/pay/reverse), SystematicPlan, BlueSkyRegistration (ACTIVE↔EXHAUSTED, EXPIRED), OmnibusReconciliation.
- **Calculations:** forward-pricing trade date, ROA household basis (both `MARKET_VALUE_BASIS`/`HISTORICAL_COST_BASIS` variants), purchase breakpoint pricing (pinned 5-step order, tier never re-derived), CDSC waterfall, exchange pricing (same-fund load-free vs. cross-fund tier), NAV strike, materiality bps (inclusive at 50.00), distribution amounts (round-per-payment-then-sum, 24% backup withholding with tax-advantaged exemption), blue-sky capacity ledger, omnibus break/tolerance. All Decimal, ROUND_HALF_UP, at declared 2/3/4 dp.
- **Cascades:** settlement, reversal, distribution pay/reverse, and the full 5-link reprocessing sweep (correct NAV → restate settled trades → restatement ledger entries + position/class share moves → invalidate later PRELIMINARY strikes → drop provisional trades to `RECEIVED` with pricing fields cleared), each followed by household basis + `current_roa_tier_pct` recomputation.
- **Rejection order:** the PRD §2.7 29-step precedence is implemented literally per endpoint (auth → role → shape → path 404 → body-FK 404 → ownership → dealer channel → OCC 412 → account state → transition → restriction → SoD → late-trade → as-of → … → capacity → share sufficiency).
- **Storage:** pure in-memory dicts; **no seeding** (verified: a fresh boot returns `total_count: 0`).

Validated with ~170 assertions across five scenario suites (all passing, zero 500s), plus a cold-boot check through `bash start.sh` on the default port.

## Step 7: Run Tests and Iterate — 2026-08-16T09:05:00.000Z

The 8-round parallel stability sweep is clean on the first iteration. Exiting per the protocol.

## Summary

**Iterations run:** 1 (single 8-round parallel sweep; no fix/rerun cycles were needed)

**Result:** All 8 concurrent rounds returned `passed == total == 95`, with `failed=0`, `errors=0`, `skipped=0`. The union of failing tests across all 8 rounds is **empty** — no flakiness surfaced, so no test entered the diagnostic protocol (STEP 0 produced an empty union set, and STEPs 1–3 were therefore not triggered).

**Tests deleted:** None. No test failed in any round, so no PRD-silence or unique-derivability analysis was warranted. Deleting a passing test would violate the cardinal rule (deletion criterion is coverage + derivability applied to *failing* tests, never difficulty or style).

**Fixes applied to `test_helpers/`:** None required.

**Fixes applied to `implementation/`:** None required.

### Integrity checks performed alongside the sweep

- **No suppressed tests:** `grep` for `pytest.mark.skip`, `pytest.mark.xfail`, `pytest.skip(` across `test_suite/` and `test_helpers/` returns nothing — the 95 passes are genuine, not skipped.
- **Collection is stable and complete:** all 8 rounds collected the *identical* frozenset of 95 test names, and that matches the 95 `def test_` functions in `/home/ubuntu/github/CodingPRD/tasks/task_2105_mutual_fund_transfer_agency/test_suite/*.py` — no test was silently dropped in any round.
- **Storage is in-memory only:** `/home/ubuntu/github/CodingPRD/tasks/task_2105_mutual_fund_transfer_agency/workspace/implementation/db.py` uses plain Python dicts on a `Store` object that starts empty on every boot; a grep for `sqlite`, `open(`, `json.dump`, `pickle`, `/tmp`, `shelve`, `redis`, `psycopg` across the implementation finds no hits. `start.sh` re-invocation under `--isolation per-test-server` therefore wipes all state, which is consistent with every round producing identical results.
- **No seeded entities:** no startup data registration exists; every fund, class, account, NAV, trade, distribution, plan, registration, case and reconciliation the tests need is built by `test_helpers/fixtures.py` through declared endpoints.

### Notes for the generators

No feedback items to forward — there were no Zero-Silence Rule violations for doc-generator and no unique-derivability misses for unit-test-generator, since no test required interpretation adjudication this run.

One observation worth flagging for future runs of this task: each round takes roughly 13–15 minutes of wall time because per-test-server isolation reboots Flask before each of the 95 tests. Running the 8 rounds concurrently keeps total wall time at about that same figure rather than 8× it, so an outer timeout sized for a single round (~20 min) is the right budget.

### Orchestrator verification (independent of subagent report)

- All 8 `results.{1..8}.json`: `passed=95 failed=0 total=95 errors=0 skipped=0`.
- `test_suite/*.py` contains 95 `def test_` functions; 95 `Design:` tags (37 `Difficulty/`, 58 `Corner/`).
- Zero `pytest.mark.skip` / `pytest.mark.xfail` / `pytest.skip(` occurrences in `test_suite/` or `test_helpers/`.

## Step 8: Finalize PRD — SKIPPED

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. `PRD.md` already determined every behavior the implementation exhibits at the sites Step 7 would have targeted. No `PRD_FINALIZED.md` is produced; Step 9 therefore starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-16T18:05:00.000Z

`/home/ubuntu/github/CodingPRD/tasks/task_2105_mutual_fund_transfer_agency/workspace/PRD_COMPLETED.md` is written.

## Source vs. completed

| | PRD.md (source) | PRD_COMPLETED.md |
|---|---|---|
| Lines | 435 | 435 |
| Chars | 112,352 | 117,714 (**+5,362**) |

Section headers (110 `#` lines) and table rows (110 `|` lines) unchanged — every change is an in-paragraph insert or revision; no new sections, no new paragraphs.

## Counts
- **Ambiguity pins (PRD silent):** 26
- **Mismatch revisions (PRD said otherwise):** 4

## Changes

- §2.3 Pagination — insert — ambiguity — out-of-range/non-integer `limit`, negative `offset`, and unrecognized enum/date filter values all answer `ERR_INVALID_REQUEST` (no clamping) — `validation.py:143-166,169-175`
- §2.5 Record Identity — insert — ambiguity — `created_at`, `updated_at`, `api_request_timestamp` come from real server time, not the logical clock — `db.py:57,84`, `response.py:20`
- §2.5 Record Identity — insert — ambiguity — `version` advances exactly once per mutating request; a no-op derived recompute advances nothing — `db.py:69-108`
- §3.1 Share Classes — insert — ambiguity — duplicate `class_code` within a fund → `ERR_INVALID_REQUEST` — `routes/funds.py:85-87`
- §3.1 Share Classes — insert — ambiguity — `twelve_b_one_fee_pct` is 4dp, non-negative, otherwise unbounded — `routes/funds.py:80-81`
- §3.2 Account Lifecycle — revise — ambiguity — restrict/reinstate from a wrong state also answer `ERR_ACCOUNT_NOT_ACTIVE`; a close blocked by non-zero shares is `ERR_ACCOUNT_NOT_ACTIVE`, one blocked by an open unsettled order is `ERR_INVALID_TRADE_STATE` — `routes/accounts.py:171,192,206,211,218`
- §3.2 Account PATCH — insert — ambiguity — link rewritten only when key present (explicit null unlinks); empty PATCH accepted and still bumps `version` — `routes/accounts.py:120,130-139`
- §3.3 NAV Strike — insert — ambiguity — weekend `valuation_date` → `ERR_INVALID_REQUEST` — `routes/navs.py:24-25`
- §3.4 Registration Expiry — insert — mismatch — the `ACTIVE → EXPIRED` sweep runs only on purchase-side capture and only for the resolved class (target class for an exchange) + account `state_code`; refusal follows only when no other window covers the date — `services/capture.py:53-58`, `services/bluesky.py:19-30`
- §3.4 Order Capture — insert — ambiguity — client-supplied `trade_type: REINVESTMENT` on `POST /trades` → `ERR_INVALID_REQUEST` — `routes/trades.py:33-34`
- §3.4 Eligibility — insert — mismatch — for an `EXCHANGE` both funds are checked for `CLOSED_TO_NEW`, target first then source — `routes/trades.py:80-84`, `services/capture.py:86-88`
- §3.5 Pricing Variants — revise — ambiguity — the variant is decided by the source class's record alone; the target record is checked only for existence and usability — `routes/trades.py:166-190`
- §3.5 Purchase Pricing — insert — ambiguity — which priced fields are left null for a purchase vs. a redemption — `services/pricing.py:28-31,66-69`
- §3.5 Redemption CDSC — insert — ambiguity — missing position or null `first_purchase_date` yields `cdsc_amount` `0.00` — `services/pricing.py:47-48`
- §3.5 Exchange Pricing — insert — ambiguity — target load pct is recorded as `sales_load_pct` (`0.0000` same-fund); `roa_qualifying_amount`/`roa_basis_variant` written only cross-fund, from the stored `household_basis_amount` un-revalued — `services/pricing.py:77-92`
- §3.6 Cancellation — revise — mismatch — the guard is on state, not on role pairing, so either `TransferAgentOperator` or `ComplianceOfficer` may drive any of the four cancel transitions — `routes/trades.py:216,221-222`
- §3.6 Cancellation — insert — ambiguity — only a `PURCHASE` holds reserved capacity, so a cancelled redemption/exchange releases nothing — `routes/trades.py:228-230`
- §3.6 Reversal — insert — ambiguity — all three reversal guards (not settled, reinvestment, would-be-negative balance) answer `ERR_INVALID_TRADE_STATE` — `routes/trades.py:241-248`
- §3.6 Reversal — insert — mismatch — reversing an `EXCHANGE` unwinds the source side only; target position, target class balance and target registration `consumed_amount` are untouched — `services/settlement.py:194-213`
- §3.7 Declaration — insert — ambiguity — `ex_date < record_date` or `pay_date < ex_date` → `ERR_INVALID_REQUEST` — `routes/distributions.py:35-38`
- §3.7 Payment — insert — ambiguity — the system-created `REINVESTMENT` order's `trade_date` (= `ex_date`), `received_at`, `captured_by_user_id`, `pricing_variant`, `nav_per_share_applied`, and null `gross_amount`/`shares_requested`/`blue_sky_registration_id` — `routes/distributions.py:172-205`
- §3.7 Reversal — insert — ambiguity — refusal code is `ERR_INVALID_DISTRIBUTION_STATE`; optional `reversal_reason` is stamped onto each reinvestment order, not the distribution — `routes/distributions.py:246,259-261,281-282`
- §3.7 Reversal — revise — ambiguity — `reinvest_nav_per_share` is preserved alongside `payment_count` — `routes/distributions.py:293-297`
- §3.8 Plan PATCH — insert — ambiguity — `amount` re-size accepted in any status incl. `TERMINATED`; empty PATCH accepted and bumps `version` — `routes/plans.py:148-151`
- §3.8 Plan Resume — insert — ambiguity — non-`ACTIVE` owning account on resume → `ERR_INVALID_PLAN_STATE` — `routes/plans.py:137-139`
- §3.8 Plan Execution — insert — ambiguity — no priced NAV on the source class → `ERR_NAV_NOT_AVAILABLE` — `routes/plans.py:196-199`
- §3.8 Plan Execution — insert — ambiguity — `SYSTEMATIC_EXCHANGE` has no market-value guard; oversized runs fail on `ERR_INSUFFICIENT_SHARES` — `routes/plans.py:188-200`, `services/capture.py:67-75`
- §3.9 Reprocessing link 2 — insert — ambiguity — purchase/reinvestment reprice as `net_invested_amount ÷ corrected NAV`; redemption/exchange keep `-shares_requested` (zero delta) yet still count; loads, proceeds and `cost_basis_amount` are not rewritten — `routes/cases.py:167-177`
- §3.9 Reprocessing link 3 — insert — ambiguity — no restatement ledger entry is written for a `0.000` delta — `routes/cases.py:185`, `services/positions.py:87-88`
- §3.10 Adjustment — insert — ambiguity — "booked dollar magnitude" = `gross_amount` (PURCHASE) / `gross_proceeds_amount` (REDEMPTION, EXCHANGE) / `net_invested_amount` (REINVESTMENT) — `routes/recons.py:21-28`

Note: §3.8's `next_run_date` base was checked (`routes/plans.py:211-212` advances from the plan's existing `next_run_date`, not the run date) — the existing PRD wording "its `next_run_date` advances by one month…" already reads that way, so no edit was made there.
