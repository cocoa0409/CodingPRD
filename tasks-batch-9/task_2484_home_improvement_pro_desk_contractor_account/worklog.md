# Worklog — task_2484_home_improvement_pro_desk_contractor_account

## Step 1: Create task directory — 2026-09-02T23:52:56.450Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2484_home_improvement_pro_desk_contractor_account` and its `workspace/` subdirectory. Index 2484 was pre-assigned by the orchestrating caller; no scan of `./tasks/` was performed (other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-03T01:26:16.722Z

All three artifacts are complete and the linter is clean.

Lint verdict (verbatim):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2484_home_improvement_pro_desk_contractor_account/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2484_home_improvement_pro_desk_contractor_account/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2484_home_improvement_pro_desk_contractor_account/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    79
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     55
  Calls scanned (§1.8+§1.9):  849

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2484_home_improvement_pro_desk_contractor_account/`):
- `SCAFFOLD.yaml` — keys exactly `scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles` (no design keys).
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`.

Counts:
- 15 entities, 11 state machines, 2 concurrency (OCC) rules, 8 calculations, 49 prioritized validations, 79 endpoints, 62 errors, 6 roles.
- §1.8: 9 rule families × 2 = 18 instances (dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant).
- §1.9: 65 instances across all 9 sections — entities 11, state_machines 14, calculations 12, validations 12, endpoints 3, errors 4, rbac 4, cross_cutting_complexity_layers 4, consistency_model 1. 55 carry full test recipes; 10 are `excluded_because` stubs, every one pointing at a real §1.8 instance name.
- 83 instance names in total, all unique across the union of both design files; all 62 declared error codes are exercised by at least one instance.

Design adjudications worth flagging:
- Certificate expiry is strict — `expires_on` must be strictly after the clock date; the entity-field description originally implied inclusivity and was harmonized with validation 36, the SM precondition, and `ProAccount.tax_exempt_state_codes`.
- `MAX_QUOTE_ROUNDS` gates both `counter-offers` and `revise` (validation 37), so the round-limit corner had to be restructured to 3 counters + 2 revises with the blocked revise as trigger (409), rather than a 4th counter.
- Priorities 21 (delivery window) and 22 (will-call stage window) were overlapping in prose; 21's check text was rewritten to cross-reference rather than duplicate 22.
- Rebate clawback targets the newest `ACCRUING` **or** `PAYABLE` accrual — that is what makes a post-close return starve a pay-out into `ERR_NO_REBATE_PAYABLE` while the accrual stays `PAYABLE`.
- The freeze threshold corner uses limits 91365 vs 91367 against an identical 82229 exposure, which pins both the `>=` comparator and `round_half_up` at an exact `.5` (91365 × 0.90 = 82228.5 → 82229).
- `ReturnRequest.reason_code` enum is `OVER_ORDERED | DAMAGED | JOB_CANCELLED | WRONG_ITEM`; an earlier draft used a non-enum value and was corrected.
- No sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-09-03T01:26:38.317Z

Copied `./INSTRUCTION.md` (1424 bytes) to `tasks/task_2484_home_improvement_pro_desk_contractor_account/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-03T01:43:32.284Z

PRD generation is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2484_home_improvement_pro_desk_contractor_account/workspace/PRD.md`

**Final size:** 505 lines, 14,737 words. **Last section heading:** `## 5. Error Code Catalogue` — the file ends at the final row of that table (`` | `ERR_NO_REBATE_PAYABLE` | 422 Unprocessable Entity | ``), a real section boundary, not mid-sentence.

**Structure:** §1 Introduction; §2 with 11 subsections (2.1 Identity/Roles, 2.2 API Response Structure verbatim, 2.3 Pagination, 2.4 Logical Clock, 2.5 Identifiers/Timestamps/Versions, 2.6 Money & Rounding, 2.7 Stale-View Protection, 2.8 Path/FK Resolution & Account Scoping, 2.9 Pro Tier Ladder, 2.10 Cascade Discipline & Parallel Dimensions, 2.11 Rule Evaluation Order with all 49 rungs); §3 with 9 workflow subsections (stores/fleet, accounts & trailing-volume tiering, credit, exemption certificates, quote negotiation cycle, order pricing/totals, multi-store sourcing, will-call & delivery, invoicing/rebates/settlement/returns); §4 Endpoint Definitions (79-row 4-column table); §5 Error Code Catalogue (62-row 2-column table).

The two withheld design files were never opened, grepped, or referenced. Only two fenced code blocks exist in the document, both the JSON envelopes inside the fixed §2.2 block (verified byte-identical to `section-2.2-response-structure.md`); no pseudocode anywhere. A fuzzy-language scan over the whole document returned zero hits. No audit footer was written into the PRD.

Hard Contract reports:

```
Field coverage check:
- entities[].fields: 121 required, 121 present, 0 missing
- endpoints[].request_body: 59 required, 59 present, 0 missing
- endpoints[].query_params: 17 required, 17 present, 0 missing
- path parameters: 15 required, 15 present, 0 missing
Status: PASS
```
(140 unique identifiers; two passes run, and a third confirming all 140 appear in §1–§3 prose rather than only in the §4/§5 tables.)

```
Rule coverage check:
- validations[] with priority: 49 checked, 49 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 51 checked, 51 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed, 0 missing
- validations[] conditions: 49 checked, 49 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 79 checked, 79 expressed, 0 missing
- entities[].fields[] structured content: 153 checked, 153 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked, 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 927
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Two notes for the caller. First, the §4 table's 79 paths were diffed set-wise against `endpoints[].path` in the scaffold and match exactly; the 62 error rows likewise. Second, the scaffold has an internal inconsistency on `ProAccount.rebate_accrued_cents` (the entity description says the sum of `accrued_cents − clawed_back_cents`, while `rebate_accrual_and_clawback` says the sum of `payable_cents` over accruals whose `payout_status` is `ACCRUING` or `PAYABLE`) — I wrote the calculation's reading, phrased so it also satisfies the entity description, since `payable_cents` is that difference floored at zero.

**Orchestrator truncation check:** independently verified — 505 lines, 5 top-level sections (`## 1.` … `## 5.`), tail is a complete error-catalogue table row. Not truncated; no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T02:22:18.672Z

(Launched concurrently with Step 6 in a single orchestrator message, per the skill's physical-isolation requirement.)

All audits pass. Final state:

## Files written

**Stage 1 — `test_helpers/`** (9 files, authored by me):
`/home/ubuntu/github/CodingPRD/tasks/task_2484_home_improvement_pro_desk_contractor_account/test_helpers/` — `__init__.py` (barrel), `types.py` (UserRole + 19 enums + 15 TypedDicts), `api_client.py` (`ApiClient` covering all 79 endpoints + module-level `api_client`), `api_errors.py` (62-member `ApiErrorId` + `HTTP_STATUS_CODES` + `set_error_http_status_map`), `constants.py` (all 14 calculation constants, tier table, SKUs, clock start), `test_users.py` (`make_contractor_admin_headers` + per-role builders), `factories.py` (15 payload factories), `assertions.py` (per-resource + invariant checkers), `fixtures.py` (5-tier composite setup helpers).

**Stage 2 — `test_suite/`**: `conftest.py` + 13 numbered files, `test_01`–`test_07` (queue A) and `test_08`–`test_13` (queue B).

## Test counts

| Queue | Files | Test functions | Instances covered |
|---|---|---|---|
| A (Difficulty §1.8) | test_01–test_07 | 39 | **18 / 18**, every one with ≥2 tests |
| B (Corner §1.9) | test_08–test_13 | 57 | **55 / 55** non-stub, ≥1 test each |
| Total | 13 | **96** | 118 collected items (parametrization) |

## Coverage audit results (run by me, not the subagents)

- **Design tags**: 96/96 tests carry exactly one `Design:` line, as the final docstring line, preceded by a blank line. Zero untagged, zero dual-tagged.
- **Tag resolution**: every tag's `<rule_id>`/`<section>` and `<instance.name>` matches the yaml block the instance actually lives in (verified by parsing both yamls, not by string search). Zero mismatches.
- **Stubs**: all 10 `excluded_because:` corner stubs are untranslated (no test tags them), and all 10 of their `difficulty_instance` pointers resolve to real §1.8 instances.
- **Citations**: 397 quoted strings extracted from docstrings by AST; all 397 verified as whitespace-normalised verbatim substrings of `workspace/PRD.md`. Zero misses.
- **Hygiene**: no `mark.skip`/`skipif`/`xfail`/`pytest.skip` anywhere; no "scaffold"/"§1.x"/"Table N"/`.yaml` reference in any emitted file; no test requests the shared `TEST_USERS["contractor_admin_headers"]` — all ownership-gated calls use `make_contractor_admin_headers(account["id"])`; `pyflakes test_suite/*.py` clean.
- **Collection**: `PYTHONPATH=. python3 -m pytest test_suite --collect-only -q` → **118 tests collected, 0 errors**.

## Instances skipped

**None.** All 18 difficulty instances and all 55 non-stub corner instances got tests. Seven individual *assertions* were dropped as PRD gaps rather than weakened:

1. Will-call sweep **response counters** (`expired_staging_count`, `released_reservation_count`, `reverted_order_count`) — the PRD states the sweep's effects but never specifies that endpoint's response body. Dropped in both the queue-A cascade test and the queue-B endpoint test; every observable entity-state effect is asserted instead.
2. `staging_stage_blocked_until_all_reservations_allocated` → `credit_status == UNBILLED`. PRD §3.6 says submission drives `credit_status` to `AUTHORIZED` in the same request, with no CARD exception (§3.3 confirms CARD still enters the exposure base), so the design's expectation contradicts the PRD.
3. `paid_amount_cents == null` / `payout_reference == null` after a refused rebate pay-out — §3.9 states `paid_amount_cents` defaults to 0.
4. `job_quote_starts_in_draft_with_no_negotiation_history` → `list_subtotal_cents`/`term_start`/`term_end == null`. §3.5 pins nullity only for the quote *lines'* prices and for `negotiated_total_cents`/`discount_depth_pct`.
5. `sourcing_is_all_or_nothing_across_lines_when_region_stock_falls_short` → the `subtotal_cents == 15992` literal. The recipe's two lines share one SKU, which contradicts §3.6 ("one line per SKU per order"); the shape was adapted to two SKUs and the shape-dependent money literal dropped rather than recomputed.
6. `appointment_guards_reject_dead_trucks_bad_access_and_empty_windows` → the recipe's `ALLEY` access type is not a declared enum value (it would trip rung 5 `ERR_INVALID_REQUEST`, not `ERR_JOBSITE_ACCESS_UNSUPPORTED`); substituted the declared `DRIVEWAY` against a `["CURBSIDE"]`-only truck, asserted error id unchanged.
7. Freeze-threshold corner → the frozen line's `available_cents` for the limit-91365 case (no literal supplied; deriving it would mean recomputing money).

Two deliberate narrowings worth relaying: ISO instants are compared through local normalizers (§2.5 mandates three fractional digits while the design writes bare `Z` instants), and rate fields (`tier_discount_pct`, `discount_depth_pct`, `restocking_fee_pct`) use `pytest.approx` with a tolerance orders of magnitude tighter than the PRD's stated 4-decimal precision. All money is exact integer-cent equality copied verbatim from the design yamls.

`workspace/implementation/` was never read or written by me or any of the six subagents.

## Step 6: Generate implementation — 2026-09-03T02:22:18.672Z

(Launched concurrently with Step 5 in a single orchestrator message.)

## Result

Implementation complete and verified. `/home/ubuntu/github/CodingPRD/tasks/task_2484_home_improvement_pro_desk_contractor_account/workspace/implementation/`

**Files written** (22 files, ~2,940 lines of Python, no data files, no `__pycache__` left behind):
- `start.sh` (executable launcher, guarded flask install, `exec python3 app.py`), `requirements.txt`, `app.py`
- Infrastructure: `clock.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `validate.py`
- `routes/`: `config.py` (11 endpoints), `accounts.py` (15), `quotes.py` (14), `orders.py` (16), `logistics.py` (13), `finance.py` (10), `__init__.py`
- `services/`: `money.py`, `stock.py`, `tier.py`, `credit.py`, `pricing.py`, `sourcing.py`, `fulfillment.py`, `returns_calc.py`, `rebate.py`, `__init__.py`

**Endpoints: 79/79.** Verified programmatically by diffing Flask's `url_map` against the SCAFFOLD `endpoints:` table — zero missing, zero extra. (The SCAFFOLD complexity note's "61" is stale; the table has 79.)

**Boot contract:** three consecutive cold boots via `start.sh` reached HTTP 200 in ~0.6 s each with `total_count: 0` on every table. Storage is a plain dict-of-dicts (`db.data`); `grep` confirms zero `open()`/sqlite/pickle/`/tmp` usage, and `PYTHONDONTWRITEBYTECODE=1` keeps the tree clean.

**Verification:** four end-to-end smoke suites, all green, covering the full happy path (account → credit line → certificate verify → quote submit/counter/approve/accept → order submit → reserve → allocate → stage → pick-up → invoice → return approve/credit → pay → rebate close/pay-out), plus the pinned arithmetic: per-unit rounding `1999 × 0.92 = 1839 → ×7 = 12873`, freight waiver at subtotal ≥ 250000, lift gate never waived, `discount_depth_pct` at 4 dp, rebate `90`-day periods with clawback landing on the newest ACCRUING/PAYABLE accrual, both tier variants diverging on the same data, the 4-key sourcing waterfall with atomic rejection, and ~20 catalogued error codes at their SCAFFOLD priorities.

**One defect found and fixed during verification:** `tier.pricing_tier` was reusing the account's *persisted* `trailing_volume_cents` for `ROLLING_365_INCLUSIVE`. Since that window slides with the logical clock, it now re-runs step 1 at the pricing instant (`services/tier.py:86`), leaving PINNED_AT_REVIEW as the only variant that reads the pinned figure.

**PRD ambiguities and chosen interpretations:**
1. **Version bumps** — one per record per request (dedupe set in `flask.g`); records created in a request stay at `version: 1` even if later cascades touch them.
2. **Ladder vs prose** — §2.11's 49-rung ordering wins wherever narrative prose implies a different order (the PRD defers to it explicitly). Notably a 4th counter-offer from `COUNTERED` yields `ERR_INVALID_STATE` (rung 13), not `ERR_QUOTE_ROUND_LIMIT` (rung 37).
3. **Job-lot sourcing** — the waterfall runs identically for job-lot orders and the single-store check applies to the *finished plan*, so a 4-unit job-lot order against stores holding 3 and 4 units is rejected with `ERR_JOB_LOT_SPLIT_NOT_ALLOWED` (the plan takes 3+1) rather than being re-routed to the store that could cover it. Insufficiency (rung 43) fires inside the line loop, before the split check (rung 44).
4. **Body FKs** — present but unresolvable → that entity's 404 (rung 4); absent entirely → `ERR_INVALID_REQUEST` 400 (rung 5).
5. **Contractor scoping** — list reads are filtered to the caller's own account; single-resource reads still return 403 `ERR_ACCOUNT_SCOPE_VIOLATION`.
6. **Missing credit line** on a CREDIT_LINE submit → `ERR_CREDIT_LINE_NOT_FOUND` 404 (per §3.6 prose), not `ERR_CREDIT_LINE_FROZEN`.
7. **Lift-gate rung 19** "the store" = the truck's home store (`truck.store_id`), not the order's fulfillment store.
8. **Truck conflict** inflates only the *new* window by the buffer on both sides, closed interval, intersected against raw SCHEDULED/CONFIRMED windows. **Bay capacity** uses half-open `[stage_start, expires_at)` so adjacency is not overlap.
9. **`tax_exempt_state_codes`** is derived on every read with strict `expires_on > today`, so a certificate stops covering its state on its expiry date itself without any sweep.
10. **`rebate_accrued_cents`** — the entity table says `sum(accrued - clawed_back)` while the calculation says `sum(payable_cents)`; I followed the calculation, so an over-clawed accrual contributes 0 rather than a negative.
11. **Rebate/clawback rate** uses the tier persisted *after* the same request's tier review (document order at the invoice transition).
12. **Duplicate `(quote_id, sku)` / `(order_id, sku)`** → `ERR_INVALID_REQUEST` 400; `store_code`/`truck_code` uniqueness is *not* enforced (no catalogued error).
13. **Staging/consumption** consider only HELD/ALLOCATED reservations, so an order that reverted via the sweep and was re-reserved still stages cleanly.
14. `POST /pro/pro-orders/{id}/reserve` → 201 with `response_type: "array"` and no pagination meta. Unmatched route → `ERR_NOT_FOUND` 404; wrong method → `ERR_INVALID_REQUEST` 405.
15. Parsed datetimes are stored under `_`-prefixed keys and stripped by `db.public()`, so responses carry only scaffold-declared fields.

## Step 7: Run tests and iterate — 2026-09-03T02:43:58.499Z

Clean 8-round sweep achieved: **118/118 passing in all 8 parallel rounds.**

## Summary

**Iterations run:** 2

**Iteration 1 baseline:** 107/118 in all 8 rounds — 11 failures, identical in every round (fully deterministic, no flakiness/load artifacts).

**Tests deleted:** none. Every failing test's asserted rule was verbatim in PRD.md and uniquely derivable, so all 11 were STEP 2 / STEP 3 fixes.

**Fixes applied to `test_suite/`** (STEP 2 — test-side helper misuse, 10 of the 11 failures):
- `/home/ubuntu/github/CodingPRD/tasks/task_2484_home_improvement_pro_desk_contractor_account/test_suite/test_01_order_pricing_and_tier_ladder.py` — local helpers `_submit`, `_read_order`, `_preview` did `validate_success(...)["data"]`. The framework's `validate_success` (in `prd-bench-local-runner/.../testing/validators.py:50`) already returns `body["data"]`, so the extra index raised `KeyError: 'data'` before any assertion ran. Removed the redundant `["data"]` (3 sites). Assertions untouched.
- `.../test_suite/test_02_quote_negotiation_cycle.py` — same defect in `_write_round` and `_revise` (2 sites). Removed the redundant `["data"]`.

No `test_helpers/` change was needed — the fixtures were faithful; only these two test modules mis-consumed the shared validator.

**Fixes applied to `implementation/`** (STEP 3 — 1 real defect):
- `/home/ubuntu/github/CodingPRD/tasks/task_2484_home_improvement_pro_desk_contractor_account/workspace/implementation/routes/accounts.py`, `create_certificate()` — added `db.touch(account)` after minting the certificate. PRD §3.4 states verbatim: *"A filing lands in `status` `PENDING` and, as a mutation of the account's exemption picture, increments the owning account's `version` by one."* The implementation never bumped the account version, so a second filing replaying the pre-filing `expected_pro_account_version` was accepted instead of being rejected with `ERR_STALE_VERSION` (412) per §2.7 — breaking the OCC contract that `test_13::test_both_occ_rules_reject_writes_made_against_a_stale_parent_version` checks.

**Notes:** no assertion was weakened, no skip/xfail added, no PRD-required implementation check removed, and no endpoint/field/side-effect was added that doesn't trace to PRD prose. The temporary `_subset/` directory used for fast triage was removed; the 8 `results.*.json` files from the final green sweep remain in `workspace/implementation/`.

**Orchestrator verification:** independently confirmed all 8 `results.{1..8}.json` exist (~38.7 KB each, mtime 02:37) and each reports `passed=118 / total=118 / failed=0`. The two `test_suite/` edits (02:31) and the `routes/accounts.py` edit (02:33) both predate the final sweep, so the green result reflects the fixed tree. `_subset/` confirmed absent. Step 8 is NOT skipped — Step 7 applied 2 `test_suite/` fixes and 1 `implementation/` fix.

## Step 8: Finalize PRD — 2026-09-03T02:52:50.680Z

Done. Here is the report.

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_2484_home_improvement_pro_desk_contractor_account/workspace/PRD_FINALIZED.md`

**Line counts:** PRD.md 505 → PRD_FINALIZED.md 505 (**0.0% line delta**; one paragraph rewritten in place, no sections added).

## Changes
- **§3.2 (Contractor Accounts and Trailing-Volume Tiering), line 221** — *revise* — the `ROLLING_365_INCLUSIVE` variant no longer says the order's `list_subtotal_cents` is added to *the persisted* `trailing_volume_cents`; it now says the two-step trailing-volume computation is **re-run against the clock at the pricing instant** and the order's `list_subtotal_cents` is added to that recomputed figure, plus an explicit note that the recomputation prices the order only (not a tier review, nothing persisted) — `implementation/services/tier.py:84-91` (`pricing_tier`, rolling branch calls `compute_trailing_volume` at line 89), consumed at `implementation/services/pricing.py:49`.

**Trace to `<step_7_diff>`:** the `test_suite/test_01_order_pricing_and_tier_ladder.py` STEP 2 fix (`validate_success(...)["data"]` removal in `_submit`/`_read_order`/`_preview`) is what un-blocked `TestTierReviewModeDivergenceOnOrderPricing`, i.e. the pinned-vs-rolling tier-determination site. Inspecting that site showed impl recomputes rather than reading the persisted figure. Verified empirically: with a GOLD-making invoice aged 400 days past its review, the persisted figure stays `6_000_000`/`GOLD` while `pricing_tier` returns `MEMBER` (recomputed volume `0`) — so a fresh implementer following the original wording would price the order at `GOLD` and diverge.

## Per-edit pre-edit search log
**Edit 1 — §3.2 rolling-variant volume base**
- (a) **Subject:** which trailing-volume figure feeds the tier-ladder match when an order is priced, and whether pricing persists anything.
- (b) **Impl paths enumerated** (grep for `pricing_tier|persisted_discount|tier_by_code|tier_review(|select_tier|compute_trailing_volume|trailing_volume_cents` across `implementation/`, then read each):
  - `services/tier.py:51-65` `compute_trailing_volume` (window, inclusive ends, `INVOICED`/`PAID` only) — the function my new wording points at.
  - `services/tier.py:68-77` `tier_review` (persists all three figures + `tier_reviewed_at`), called from `routes/accounts.py:47` (create), `routes/accounts.py:79` (volume adjustment), `routes/orders.py:391` (invoice), `routes/finance.py:209` (return credit) — the four tier-review events; unchanged by my wording.
  - `services/tier.py:84-91` `pricing_tier` — rolling branch recomputes; pinned branch reads persisted `tier_code` via `tier_by_code`.
  - `services/pricing.py:27-131` `compute` — the only caller (`persist=True` on submit, `persist=False` on `pricing-preview` per `routes/orders.py:181-189`, `192-249`); it never writes account tier fields, confirming the "not a tier review" clause.
  - Parallel persisted-tier consumers deliberately left untouched: `services/rebate.py:13` (rebate rate from persisted `tier_code`), `services/returns_calc.py:61` (`persisted_discount` for `CURRENT_LIST` returns), `routes/quotes.py:291` (`max_quote_term_days` at quote acceptance).
- (c) **Wording adjustments made:** scoped the sentence strictly to *order pricing under `ROLLING_365_INCLUSIVE`* so the `PINNED_AT_REVIEW` clause, the four tier-review events, and the rebate/returns/quote-term consumers of the persisted tier keep reading exactly as before; added the "only prices the order / not a tier review / re-stamps nothing" clause so the recomputation can't be mistaken for a fifth review event (which would contradict `test_01`'s second test and `tier_review`'s callsites).

## Items examined and deliberately NOT patched
- **STEP 3 impl fix — `routes/accounts.py:195` `db.touch(account)` in `create_certificate()`:** PRD §3.4 ("A filing lands in `status` `PENDING` and, as a mutation of the account's exemption picture, increments the owning account's `version` by one") plus §2.7/§2.11 rung 6 already determine this uniquely, and impl now bumps by exactly one (`db.touch` bumps once per record per request; the account is not the record created in that request). Check order in impl (FK resolution → shape → stale-version → scope) already matches §2.11 rungs 4→5→6→7. No edit.
- **STEP 2 test fixes in `test_01`/`test_02`:** pure test-side misuse of `validate_success` (which already returns `body["data"]`). Every assertion they unblocked — per-unit rounding before multiply (1839/12873), freight waiver keyed on `subtotal_cents` at the inclusive $2,500 threshold, lift-gate fee never waived, preview persisting nothing, counter-offer/revise counters, round supersession, `discount_depth_pct` to four decimals — is verbatim PRD prose and matches `services/pricing.py` / `routes/quotes.py`. No edit.
- **Out-of-scope observation (not patched, flagged only):** `db.touch` (`implementation/db.py:61-70`) bumps a record's `version` **at most once per request**, so a single request whose cascade mutates the same record twice (e.g. invoice → `recompute_exposure` then `utilization_review` freeze on one credit line) yields +1, not +2, which reads narrower than §2.10's "exactly as if the change had been requested directly". No Step 7 item touches this, so PRD_FINALIZED leaves §2.5/§2.10 verbatim.

**Orchestrator verification:** `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (221), both files 505 lines. No truncation, no new sections.

## Step 9: Complete PRD — 2026-09-03T03:13:29.727Z

Done. Final verification: 505 lines, tail ends at the real §5 boundary (`ERR_NO_REBATE_PAYABLE` row).

## Result

- **Source vs output:** `PRD_FINALIZED.md` 505 lines / 106,312 chars → `PRD_COMPLETED.md` **505 lines** / 115,244 chars (**+8,932 chars**). Line count unchanged because every change is an in-paragraph insert or revision — no new paragraphs, no new sections. Tail verified: file ends with `| ERR_NO_REBATE_PAYABLE | 422 Unprocessable Entity |`.
- **Counts:** 28 ambiguity-pins, 15 mismatch-revisions (43 pinned behaviors across 39 edits).

### Changes
- §2.1 — insert — ambiguity — ContractorAdmin collection reads are silently narrowed to own-account records (affecting `total_count`), not rejected — `middleware.py:59`
- §2.2 — revise — ambiguity — `api_request_timestamp` is read from the logical clock, not wall time — `response.py:16`
- §2.2 — revise — ambiguity — pagination fields appear on list reads only; the sourcing array response carries none — `routes/orders.py:266`
- §2.3 — revise — ambiguity — `offset` must be a non-negative integer; non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; over-range offset yields an empty page — `validate.py:135-151`
- §2.3 — insert — ambiguity — identical `created_at` values tie-break by write order, globally (incl. §3.7 sourcing) — `db.py:87`
- §2.3 — insert — ambiguity — filters are exact-match, conjunctive; unmatched value → empty page; undocumented params ignored — `routes/config.py:49-96`
- §2.5 — revise — mismatch — `version` increments at most once per record per request; a record created by a request stays at 1 even when a later cascade of that request rewrites it — `db.py:56-70`
- §2.11 r4 — revise — ambiguity — full body-FK list (adds `originating_store_id`, `store_id`, `pro_order_id`, `quote_line_id`); a present-but-unresolvable reference of any JSON type is the 404, absent falls to rung 5 — `validate.py:168-179`
- §2.11 r5 — insert — ambiguity — undeclared body fields are ignored — `validate.py:14-22`
- §2.11 r17 — revise — mismatch — only *live* reservations must be `ALLOCATED`, and at least one must exist — `routes/logistics.py:110`
- §2.11 r19 — revise — mismatch — lift-gate yard check reads the truck's home store — `routes/logistics.py:190`
- §2.11 r26 — revise — mismatch — `ERR_NO_ORDER_LINES` also guards the sourcing call — `routes/orders.py:261`
- §2.11 r27 — revise — mismatch — `ERR_SKU_NOT_STOCKED` also fires from both order-pricing runs — `services/pricing.py:43`
- §3.1 — revise — mismatch — `store_code` uniqueness is never tested — `routes/config.py:26`
- §3.1 — revise — ambiguity — store fields required with no default (incl. `lift_gate_available`) — `routes/config.py:28-34`
- §3.1 — revise — mismatch — `truck_code` uniqueness never tested; `lift_gate_equipped` required — `routes/config.py:111`
- §3.1 — revise — mismatch — out-of-service `reason_code` is required but not persisted; repeat → `ERR_INVALID_STATE` — `routes/config.py:146-150`
- §3.2 — revise — ambiguity — `delta_cents` any signed integer, `memo` non-empty, baseline may go negative (→ `MEMBER`), response is the account — `routes/accounts.py:76-80`
- §3.3 — revise — mismatch — opening a credit line recomputes exposure, so pre-existing AUTHORIZED/INVOICED orders are already in the base — `routes/accounts.py:118`
- §3.3 — revise — mismatch — manual freeze stores the supplied `reason_code` verbatim, not `MANUAL` — `services/credit.py:38`
- §3.3 — insert — ambiguity — account reinstate with no credit line → `ERR_CREDIT_LINE_FROZEN`; not on HOLD → `ERR_INVALID_STATE` — `routes/accounts.py:87-91`
- §3.4 — insert — ambiguity — filing never tests `expires_on` against the clock — `routes/accounts.py:179`
- §3.4 — insert — ambiguity — verify/revoke bump the account's `version`; non-`PENDING` verify → `ERR_INVALID_STATE` first — `routes/accounts.py:229`, `:220`
- §3.5 — revise — ambiguity — duplicate quote-line SKU → `ERR_INVALID_REQUEST`; line added outside `DRAFT` → `ERR_INVALID_STATE` — `routes/quotes.py:100-107`
- §3.5 — revise — ambiguity — counter-offer `term_days` required, minimum 1 — `routes/quotes.py:207`
- §3.6 — revise — mismatch — order creation defaults: `tax_exempt_applied` false and the two credited-refund fields 0, not null — `routes/orders.py:80-86`
- §3.6 — revise — ambiguity — duplicate order-line SKU → `ERR_INVALID_REQUEST`; line outside `DRAFT` → `ERR_INVALID_STATE` — `routes/orders.py:123-130`
- §3.6 — insert — ambiguity — preview `data` is exactly the nine fields, can report `ERR_SKU_NOT_STOCKED`, and no other guard applies — `routes/orders.py:181-189`
- §3.6 — revise — ambiguity — submission also sets `net_volume_cents`; a `CARD` submission recomputes no credit line — `routes/orders.py:242-248`
- §3.7 — insert — ambiguity — reserve returns the created reservations as a 201 array in plan order, no pagination — `routes/orders.py:266`
- §3.7 — revise — ambiguity — release `reason_code` is any non-empty string, stored verbatim — `routes/orders.py:315`
- §3.8 — revise — mismatch — stage tests only live reservations; none live → `ERR_RESERVATIONS_NOT_ALLOCATED` — `routes/logistics.py:109-111`
- §3.8 — insert — ambiguity — sweep response counters `expired_staging_count` / `released_reservation_count` / `reverted_order_count` — `routes/logistics.py:162-166`
- §3.8 — revise — mismatch — lift-gate check uses the truck's home store — `routes/logistics.py:190-193`
- §3.8 — revise — mismatch — confirm re-tests only `OUT_OF_SERVICE` (no `MAINTENANCE` state exists) — `routes/logistics.py:256`
- §3.8 — revise — mismatch — completion needs ≥1 live reservation; released ones ignored, none live → `ERR_INVALID_STATE` — `routes/logistics.py:274-276`
- §3.9 — insert — ambiguity — the invoice books the rebate delta after its own tier review — `routes/orders.py:391-392`
- §3.9 — revise — ambiguity — accrual rate is the rung the invoice just persisted — `services/rebate.py:61`
- §3.9 — revise — ambiguity — `payout_reference` required non-empty — `routes/finance.py:70`
- §3.9 — revise — ambiguity — return `qty_units` integer ≥1; each entry checked individually, duplicates both valued/credited — `routes/finance.py:104-115`
- §3.9 — revise — ambiguity — `valuation_mode` consults only `term_end` (quote status/`term_start` irrelevant; null → `CURRENT_LIST`) — `services/returns_calc.py:34-39`
- §3.9 — insert — ambiguity — `CURRENT_LIST` falls back to the order line's snapshotted list price when the stock position is gone — `services/returns_calc.py:56-60`
- §3.9 — revise — ambiguity — clawback rate is the post-hop-3 (possibly demoted) tier — `routes/finance.py:209-211`

**Orchestrator verification:** `PRD_COMPLETED.md` is 505 lines / 115,244 chars with all 5 top-level sections present and the tail at the final §5 error-table row — not truncated. `diff PRD_FINALIZED.md PRD_COMPLETED.md` shows 40 changed lines (in-paragraph revisions only, no line-count change). Steps 8 and 9 touched only PRD documents, so the Step 7 green sweep (8/8 rounds, 118/118) remains the valid test record.

## Pipeline complete — 2026-09-03T03:13:29.727Z

All nine steps finished. Final artifacts: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `test_helpers/` (9 files), `test_suite/` (conftest + 13 test modules, 118 collected tests), `workspace/INSTRUCTION.md`, `workspace/PRD.md`, `workspace/PRD_FINALIZED.md`, `workspace/PRD_COMPLETED.md`, `workspace/implementation/` (22 files, 79 endpoints, in-memory only) with `results.{1..8}.json` from the final all-green sweep.
