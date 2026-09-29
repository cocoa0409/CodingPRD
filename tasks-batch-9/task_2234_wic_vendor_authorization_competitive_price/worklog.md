# Worklog — task_2234_wic_vendor_authorization_competitive_price

## Step 1: Create task directory — 2026-09-01T00:00:00.000Z

Created `tasks/task_2234_wic_vendor_authorization_competitive_price/` and `tasks/task_2234_wic_vendor_authorization_competitive_price/workspace/` (pre-allocated name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T10:26:00.000Z

All three artifacts are complete and lint-clean.

**Lint verdict (verbatim, final run):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2234_wic_vendor_authorization_competitive_price/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2234_wic_vendor_authorization_competitive_price/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2234_wic_vendor_authorization_competitive_price/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    58
  §1.1 entities declared:     12
  §1.8 instances scanned:     19
  §1.9 instances scanned:     41
  Calls scanned (§1.8+§1.9):  852

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2234_wic_vendor_authorization_competitive_price/`): `SCAFFOLD.yaml` (137 KB), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (123 KB), `SCAFFOLD_CORNER_DESIGN.yaml` (205 KB). Key separation verified: `SCAFFOLD.yaml` carries neither design key; each design file has exactly one top-level key.

**Scaffold counts (§1.0–§1.7)**
- 12 entities: PeerGroup, FoodCategory, AuthorizedFoodItem, Vendor, PriceCycle, PriceSubmission, PriceCeiling, MonitoringVisit, RedemptionClaim, ClaimLine, ReimbursementAdjustment, SanctionCase
- 7 state machines / 37 transitions (Vendor is cyclic via the reauthorization loop; SanctionCase forks CMP vs disqualification and rejoins at CLOSED; PriceSubmission has a bounded REJECTED→SUBMITTED loop)
- 2 concurrency rules (OCC on `expected_claim_version` and `expected_vendor_version`, distinct 412 error ids)
- 13 calculations, 2 of them dual-variant (`maximum_allowable_reimbursement` PROVISIONAL/FINAL, `vendor_risk_score` ROLLING/EPOCH)
- 42 ordered validations (auth 1–4, SoD 20, then referential → duplicate → temporal → OCC → state → business_safety → business_fiscal)
- 58 endpoints, 58 errors, 5 roles (VendorOperator entity-backed; segregation-of-duties role model)

**Design-file instance counts**
- §1.8: 19 instances across all 9 required rule_ids (3 for `combinatorial_formula`, 2 each for the rest)
- §1.9: 60 instances across all 9 guide sections — 41 full recipes + 19 `excluded_because` stubs (entities 9, state_machines 9, calculations 7, validations 6, endpoints 4, errors 13, rbac 5, cross_cutting_complexity_layers 5, consistency_model 2)

**Verification performed beyond the linter**
- Name uniqueness across the union of both files: no collisions; all 19 stub `difficulty_instance` references resolve to real §1.8 names; no stub carries a `test_recipe`; every stub has `claim_type` + `grounds` (this was a real gap — grounds were missing on all 19 stubs and were added).
- Enum audit of every payload value against §1.1 `constraints`: found and fixed one defect — `formula_restriction_level: "RX_ONLY"` (not in `NONE | CONTRACT_BRAND_ONLY | MEDICAL_DOC_REQUIRED`), which would have made a duplicate-code test return 422 instead of the intended 409. Only remaining "violation" is the deliberate invalid-enum test.
- Manual role/payload audit of the 8 instances the linter skips via its negative-name heuristic: every flag is an intentional negative (absent/undeclared role header, missing required field, extra system field, analyst on supervisor-only endpoints).
- Call-by-call replay of the state-dependent chains: confirmed `conduct` has no clock≥`scheduled_for` precondition, that back-to-back visits at 2026-08-05/08-06 clear the 7-day blackout only because the first is conducted before the second is created (ordering is correct in the file), that `POST /price-submissions` has no vendor-state precondition (so APPLICANT-vendor chains are valid), that `SUSPENDED → DISQUALIFIED` exists with the full member_count-decrement cascade, and that all arithmetic literals re-derive (CMP 300000/1800000/5625000-cap, risk 60.0 at the `>=` boundary, proration 84 and 34, MAR 336, claim total 3088).
- Structural pass over all 60 recipes: clock set as the first setup call, `trigger` always a list, `setup`/`assert` prose lists, `payload` and `as` present on every call — 0 issues.

## Step 3: Copy shared files — 2026-09-01T10:27:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_2234_wic_vendor_authorization_competitive_price/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T10:42:00.000Z

PRD written to `/home/ubuntu/github/CodingPRD/tasks/task_2234_wic_vendor_authorization_competitive_price/workspace/PRD.md`.

## Output
- **503 lines**, ends at §5 with no audit footer.
- **Sections:** §1 Introduction (3 paragraphs); §2 with 10 subsections (2.1 Role-Based Access Control, 2.2 API Response Structure — byte-identical to `section-2.2-response-structure.md`, verified by diff, 2.3 Pagination, 2.4 Resource Identity/Timestamps/Versioning, 2.5 Logical Clock and Calendar-Month Arithmetic, 2.6 Cents/Percentages/Rounding Discipline, 2.7 Request Rejection Order and Identifier Resolution, 2.8 Optimistic Concurrency on Parent Versions, 2.9 Cascade Integrity, 2.10 Segregation of Duties); §3 with 9 domain subsections (peer group + food list config; vendor intake/peer assignment/training; price cycle submission and review; MAR derivation; authorization/reauthorization/denial; monitoring visits/minimum stock/compliance-buy cascade; redemption claims and transaction edits; reimbursement adjustments; risk scoring and sanction schedule); §4 four-column table with all 58 endpoints; §5 two-column table with all 58 error IDs.

## Audit results

```
Field coverage check:
- entities[].fields: 135 required, 135 present, 0 missing
- endpoints[].request_body: 55 required, 55 present, 0 missing
- endpoints[].query_params: 19 required, 19 present, 0 missing
- inline output-object fields: 24 required, 24 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 42 checked, 42 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 7 machines / all transitions checked, all fully expressed, 0 missing
- calculations[]: 13 checked, 13 fully expressed, 0 missing
- validations[] conditions: 42 checked, 42 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 58 endpoints checked, all expressed, 0 missing
- entities[].fields[] structured content: 135 checked, reconstructible from prose, 0 missing
- sibling-branch symmetry: 5 groups checked (CMP vs. disqualification fork; PROVISIONAL vs. FINAL MAR variant; ROLLING vs. EPOCH risk basis; deny-from-IN_REVIEW vs. deny-from-REAUTH_PENDING; close-from-CMP_ELECTED vs. close-from-DISQUALIFICATION_IMPOSED), 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 947
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Endpoint table verified programmatically as an exact set match against the scaffold's 58 `(method, path)` pairs; error table verified as an exact match on all 58 `(error_id, http)` pairs. No pseudocode operators (`==`, `>=`, `+=`, `min()`, `ceil()`, `round()`, `IN {…}`) and no fuzzy hedges survive anywhere in the document.

## Elements needing careful rendering
1. **Two different governing-cycle tie-breaks.** `price_submission_completeness` picks the greatest `submission_open_at` with ties to the **greater** `created_at`, while claim adjudication and compliance-buy pricing pick the greatest `published_at` with ties to the **earlier** `created_at`. Rendered as opposite directions in prose so an implementer cannot collapse them.
2. **MAR step order and single rounding.** Allowance before cap, cap computed off the *same* candidate set that produced the base (not the peer set when the fallback fired), `cap_binding` from the strict comparison, one half-up rounding at the very end, with `base_cents`/`cap_cents` left unrounded.
3. **The four-hop failed-visit cascade**, with hops 2-4 explicitly conditional on the threshold crossing, plus the closing note that a first failure stops after hop 1.
4. **Sanction schedule single-pass order** — `case_points` from `base_tier` never `effective_tier`, cumulative snapshot over *other* cases in three statuses only, escalation step as an inclusive threshold count, no re-iteration — and the deliberate asymmetry that notice-service suspension keys off `base_tier`.
5. **Point-timing asymmetry across the fork:** branch B adds `sanction_points` at imposition and explicitly not again at closure; branch A adds them only at closure; dismissal adds none.
6. **Proration rounding order** (per line, then sum; residual not redistributed) and the three-place money reversal invariants.
7. **Boundary inclusivity** stated everywhere it decides an outcome: half-open cycle windows (touching at `submission_due_at` allowed), closed symmetric 7-day blackout, inclusive 90-day reauth window, strict `clock < training_expires_at`, `charged == mar` accepted at full price rather than reduced, and the inclusive `>= 60.0` / `>= 30.0` tier floors.
8. **Header note discrepancy:** the scaffold's banner comment says "34 validation rows, 46 error codes" but the actual `validations` list has 42 priority rows and `errors` has 58 entries. I rendered the actual lists.

## Step 5: Generate unit tests — 2026-09-01T11:20:00.000Z

Generation is complete and verified.

## Files written

**Infrastructure — `/home/ubuntu/github/CodingPRD/tasks/task_2234_wic_vendor_authorization_competitive_price/test_helpers/`** (9 files): `__init__.py` (barrel export), `api_client.py` (58 endpoint methods, one per PRD §4 row), `api_errors.py` (58-member error enum + HTTP status map registered with the framework so `validate_error` checks status automatically), `constants.py`, `types.py`, `test_users.py`, `factories.py`, `assertions.py`, `fixtures.py` (5-tier composite builders).

**Tests — `.../test_suite/`**: `conftest.py` + 13 test files, **99 tests** total.

## Coverage

| | instances | translated | skipped |
|---|---|---|---|
| Queue A (Difficulty §1.8) | 19 non-stub | **19/19** | 0 |
| Queue B (Corner §1.9) | 41 non-stub | **41/41** | 0 |

No instance failed the PRD-first filter, so nothing was skipped. The 19 `excluded_because:` corner stubs were not translated; I verified all 19 of their `difficulty_instance:` cross-references resolve to real §1.8 instance names.

## Verification passed

- `py_compile` clean; `pytest --collect-only` collects 99 tests, no errors.
- Every test has exactly one `Design:` line, as the last docstring line, resolving to a real non-stub instance; 60 distinct tags, each instance covered exactly once; every queue A instance has >=2 tests.
- Every quoted docstring sentence is verbatim-greppable in `PRD.md` (I found and fixed 8 defective citations — truncations at a `;`/`—`, stripped markdown emphasis, and one fabricated `"Hop 1 always runs"` where the PRD writes `**Hop 1** always runs`).
- No occurrence of "scaffold" or any design-index vocabulary; no skip/xfail/TODO placeholders; no mocking; all 0 dangling helper attribute references.

## PRD-vs-design contradictions, all resolved in the PRD's favour

1. **`resolution` at case open** — design said null; PRD §3.9 says `NONE`.
2. **`risk_flag` baseline** — design said null; PRD §3.2 says `NONE`.
3. **Version increments on create** — design claimed the parent version was unchanged; PRD §2.8 says adjustment-create bumps the claim version and case-create bumps the vendor version.
4. **`ERR_DISQUALIFICATION_NOT_AVAILABLE`** — design literal said 422; PRD §5 fixes 409.
5. **Timestamp precision** — design wrote bare-`Z` instants; PRD §2.5 mandates three fractional digits.
6. **Envelope key sets** — several instances asserted a body has "exactly the keys data and meta"; PRD §2.2 also mandates `response_type`, so these assert the named values without forbidding other keys.
7. **`avg_monthly_redemption_cents` on a never-authorized vendor** — one instance assumed the reported-value fallback had already run; PRD §3.2/§3.5 only run it on authorization, so that test now authorizes the vendor first.
8. **Non-derivable version deltas** — dropped `fresh == stale + 1` assertions where the PRD lets a second write intervene (submission review also mutates the vendor); those assert only that the version incremented.

## Two PRD issues worth your attention

- **Internal PRD conflict on the delist cascade's 4th hop.** §3.1 says the recompute sets `price_submission_complete` false when the delisted item was `required_for_authorization`; §3.2 says a delisted item "drops out of the required set entirely" and an empty required set satisfies the all-of test, which would make it *true*. The test asserts the action-specific §3.1 outcome.
- **No `GET /price-cycles` collection endpoint** exists in §4, so one planned "nothing was persisted" check had to be re-expressed as a re-read of the incumbent cycle.

## Step 6: Generate implementation — 2026-09-01T11:00:00.000Z

The implementation is complete and verified.

## Files written

`/home/ubuntu/github/CodingPRD/tasks/task_2234_wic_vendor_authorization_competitive_price/workspace/implementation/` — 25 files, ~3,250 lines of Python.

**Launcher / infra**
- `start.sh` — `cd` to its own dir, installs Flask only if missing (unconditional `pip install` caused boot contention under 8 concurrent per-test reboots), then `exec python3 app.py`
- `requirements.txt`, `app.py` (app factory, `strict_slashes=False`, `ApiError`/`HTTPException`/catch-all handlers all emitting the error envelope, `app.run(host="0.0.0.0", port=$PORT|10000, threaded=True, use_reloader=False)`)

**Core layer** — `config.py` (all domain constants/enums), `errors.py` (58 error ids → HTTP status + `ApiError`), `clock.py` (logical clock, `add_days`/`add_months` with day clamping), `store.py` (12 in-memory dicts, `new_record`, `touch`, `_seq` tie-break ordering), `envelope.py` (`meta`/`success`/`collection`/`error`, `Decimal`→float, datetime→ISO-3-digit), `auth.py`, `validators.py`, `calc.py` (all 12 calculations, `Decimal` + `ROUND_HALF_UP`), `models.py` (12 record factories)

**Domain layer** — `services.py` (state transitions plus the four cascade families: peer-group `member_count`, delist/void, money reversal, four-hop finding escalation; plus `risk_run`)

**Routes** — `routes/{common,peer_groups,food,vendors,price_cycles,price_submissions,price_ceilings,monitoring,claims,adjustments,sanctions,ops}.py` + `__init__.py` blueprint registration

## Endpoint count

**58/58.** Verified programmatically: the Flask url_map, normalized to method + path, is exactly equal to the 58 `method`/`path` pairs in SCAFFOLD.yaml — zero missing, zero extra.

## Verification

Boots clean from a fresh process (no traceback in any boot log). A 90-assertion smoke script exercised the full lifecycle end to end and every assertion passed:

- MAR: median(380, 420, 500) = 420 x 1.10 = **462**; publish returns `{published_ceiling_count: 1, skipped_pair_count: 0, superseded_ceiling_count: 1}`
- Claim adjudication: line 1 (2 x 900c) → `E05` / `ACCEPTED_REDUCED` / 924c, line 2 → `ACCEPTED` / 100c, net payable **1024c**
- Adjustment @ 0.5: per-line 462 + 50 = **512c** (per-line-then-sum, residual not redistributed); apply → `ADJUSTED`/512, reverse → `ADJUDICATED`/1024
- Sanctions: CLASS_C → tier 2, 2 points, CMP 307c, 6-month disqualification; CLASS_A → tier 4, notice suspends vendor, disqualification to 2029-08-01, `member_count` 3 → 2
- Risk: `risk_score` 62.5 → HIGH; `_ops/risk-run` returns all five counters
- OCC (412), SoD (403), vendor scope (403), blackout/duplicate/window conflicts, pagination meta, `req_`+20-char id, 401/403/404/405/422 all correct

Fresh restart confirms an empty store on every collection and the default logical clock `2026-08-01T00:00:00.000Z`. Storage is in-memory dicts only; nothing is seeded, and the only disk artifact was `__pycache__`, which I removed.

## PRD passages I had to interpret

1. **Ladder ordering within action handlers** — rule 7 (shape) is applied before rule 16 (state) everywhere, since the PRD pins the global ladder but not the intra-handler interleaving.
2. **`complete-reauthorization` gate order** — state → training(21) → open case(22) → hold(39) → peer group(35) → completeness(36), following §3.5 prose order rather than ladder numeric order.
3. **`revise`** — window-closed (32) checked before revision-limit (34).
4. **`apply` adjustment** — adjustment state(16) → claim already paid(18) → SoD(20) → claim must be ADJUDICATED → recoupment exceeds payable(41).
5. **Vendor scope resolution order** — for `/vendors/{id}` the path id is compared to `X-User-ID` *before* existence (403 even for a nonexistent vendor); for child entities we resolve first (404) then compare owner (403); a body `vendor_id` mismatch yields 403 before the body FK 404. **List endpoints are not vendor-scoped** and query params are not scope-checked.
6. **Body FK (rule 6) vs shape (rule 7)** — rule 6 only fires when the field is present *and* a string; otherwise rule 7 produces 422.
7. **Query-parameter enum filters are not validated** — only `limit`/`offset` and the functional `basis` are; unknown filter values simply match nothing.
8. **`version` bumping** — `services.update()` bumps only when a value actually changes (§2.4 is ambiguous about no-op writes).
9. **Idempotent retire/delist** — the 58-error catalog has no state error for peer-group retire or item delist, so both are no-ops when already RETIRED/DELISTED (200, unchanged entity).
10. **Provisional-vs-active supersede accounting** — publish supersedes this cycle's PROVISIONAL rows (`PROVISIONAL_REPLACED`) *and* earlier-cycle ACTIVE rows for republished pairs (`NEWER_CYCLE_PUBLISHED`); both count toward `superseded_ceiling_count`.
11. **Cascade hop triggers** — hop 2 at `open_finding_count >= 2`; hop 3 only on a false→true flip of `compliance_buy_required` (auto visit, `+14d`, blackout-exempt); hop 4 sets `reauthorization_hold` + `PENDING_COMPLIANCE_BUY` only when REAUTH_PENDING.
12. **`stock_findings` ordering** — observation order preserved, server-synthesized MISSING entries appended in category `code` ASC.

## Step 7: Run tests and iterate — 2026-09-01T12:15:00.000Z

Clean sweep. All 8 parallel rounds: **99/99 passed, 0 failed, 0 errors.**

## Summary

**Iterations run:** 2 full 8-round parallel sweeps (baseline sweep: 97/99 in all 8 rounds, identical failure pair every round — not flaky; final sweep: 99/99 in all 8 rounds).

**Failing tests in the union set (both in `test_suite/test_06_cascades_and_risk_scoring.py`):**
- `test_delisting_voids_the_submissions_that_fed_the_ceiling` — `AssertionError: expected 'price_submission_complete' to be False, got True`
- `test_delisting_blocks_a_pending_authorization_without_de_authorizing_anyone` — `authorize` returned 200 instead of `ERR_PRICE_SUBMISSIONS_INCOMPLETE`

**STEP 1 verdict — both tests kept.** PRD §3.1 verbatim covers the asserted rule: *"In the fourth hop, because those submissions were voided, each affected vendor's `accepted_submission_count` is decremented and its `price_submission_complete` is recomputed, turning false when the delisted item had `required_for_authorization` set to true."* Plus §2.7 rule 36 / §3.5: *"And `price_submission_complete` must be true, or `ERR_PRICE_SUBMISSIONS_INCOMPLETE`."* The tension with §3.2's general clause (*"an item that has been delisted drops out of the required set entirely"*) is resolved in favor of the sentence written specifically about the delist cascade, which names the observable outcome directly; none of the five collapse patterns applies, so unique derivability holds.

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none — fixtures, factories, and role-header builders traced faithfully to PRD (`_delist_cascade_setup` builds a required-for-authorization milk item, one AUTHORIZED and one IN_REVIEW vendor with accepted prices, a CLOSED cycle; the delist is issued by a supervisor with a free-text reason, exactly as §3.1 requires).

**Fixes applied to `implementation/` (both STEP 3, PRD-faithfulness fixes, not weakenings):**
- `workspace/implementation/calc.py` — `price_submission_completeness()`: added an `extra_required_items` argument so a recompute can be told to still treat a just-delisted item as required, which is what §3.1 hop 4's "turning false when the delisted item had `required_for_authorization` set to true" requires.
- `workspace/implementation/services.py` — `refresh_completeness()` threads that argument through; `delist_item()` hop 4 now passes the delisted item, so affected vendors' readiness actually turns false instead of becoming vacuously true once the item left the ACTIVE required set.
- `workspace/implementation/routes/vendors.py` — `authorize_vendor()`: dropped the unrequested `refresh_completeness()` call that immediately recomputed the flag back to true. §3.5 for authorize states only that "`price_submission_complete` must be true"; only complete-reauthorization is specified to evaluate it "against the current cycle", which still recomputes.

**Orchestrator note:** the Step 7 subagent removed its `results.*.json` files on exit, so the orchestrator re-ran the identical 8-round parallel sweep independently to regenerate the artifacts and confirm the pass.

## Step 8: Finalize PRD — 2026-09-01T12:17:00.000Z

Done. `PRD_FINALIZED.md` written.

## Size delta
- **Lines:** 502 → 502 (**0.0%**) — all three edits are inline inside existing sentences/paragraphs; no new lines, no new sections.
- Words 13,307 → 13,471 (+1.23%); characters 96,411 → 97,475 (+1.10%).

Note: this workspace contains only `INSTRUCTION.md`, `PRD.md`, and `implementation/` — there is no `test_suite/` or `test_helpers/` directory to consult, so alignment was done purely against `implementation/`. (Orchestrator note: `test_suite/` and `test_helpers/` live at the task root, not under `workspace/`; alignment target is `implementation/` regardless, so this did not affect the result.)

## Changes

- **§3.2 (Price submission completeness, final sentence)** — *revise* — the flat rule "an item that has been delisted drops out of the required set entirely" now carries the single exception the impl implements: the delist cascade's fourth hop, when recomputing the vendors whose submissions it just voided, still counts the just-delisted item as required if its `required_for_authorization` is true (so readiness turns false instead of vacuously true). Explicitly scoped: no other recompute applies the exception. — `implementation/calc.py:107,119-123`; `implementation/services.py:52-54,132`
- **§3.5 (Authorization, five conditions)** — *insert* — pinned that authorization tests the stored `price_submission_complete` flag as it already stands and does **not** recompute it first. — `implementation/routes/vendors.py:147-150`
- **§3.5 (Completing reauthorization)** — *revise* — pinned the counterpart asymmetry: reaching the completeness check here first recomputes `accepted_submission_count` and `price_submission_complete` against the §3.2 governing cycle, then tests the recomputed value. — `implementation/routes/vendors.py:214-216`

## Per-edit pre-edit search log

**Edit 1 — §3.2 delisted-item / required-set exception**
- (a) Subject: which items enter the required set on a completeness recompute, and whether the delist cascade differs.
- (b) Enumerated: `grep -rn "refresh_completeness|price_submission_complete|price_submission_completeness|extra_required_items|void_open_submissions|accepted_submission_count"` over all of `implementation/`. Read every hit: `calc.py:107-134` (the only place the required set is built; `extra_required_items` re-added only when the extra's `required_for_authorization` is true and not already present), `services.py:52-54` (sole wrapper), `services.py:105-132` (delist hops 1-4 — the **only** caller passing extras, and only for the `affected` vendors whose submissions the hop-3 void touched), `services.py:91-101` `void_open_submissions` → no extras (used by deny `routes/vendors.py:175` and disqualify `services.py:479`), `routes/vendors.py:130` submit-application → no extras, `routes/vendors.py:195` start-reauthorization → no extras, `routes/vendors.py:214` complete-reauthorization → no extras, `routes/price_submissions.py:110-112` review → no extras, `models.py:64-65` baselines. Also confirmed `routes/food.py:111-118` is the only delist entry point.
- (c) Adjustments made: (i) first draft enumerated by name the six non-delist recompute triggers; I replaced that with the trigger-agnostic "No other recompute of completeness, wherever it is triggered, applies that exception" so the PRD does not newly assert *that* denial/disqualification recompute readiness (true of impl, but an unrelated claim) while still fixing the exception's scope. (ii) Added the qualifier "when that item's `required_for_authorization` is true" to match `calc.py:120`. (iii) Added "recomputing the vendors whose submissions it has just voided" to match hop 4's `affected`-only loop rather than implying a global recompute.

**Edit 2 — §3.5 authorize does not recompute**
- (a) Subject: whether the authorize gate reads or recomputes `price_submission_complete`, and what else authorize mutates.
- (b) Enumerated: `routes/vendors.py:134-162` (full `authorize_vendor`: state → training → open case → peer group → stored-flag read at 149; then status/`authorized_at`/`reauthorization_due_at`/`authorization_blocked_reason`, `sync_member_count`, `refresh_avg_redemption` — no completeness refresh). Cross-checked the only other consumer of the flag, `routes/vendors.py:215`, plus every writer of the flag (same grep as Edit 1) to confirm "whatever value the last recompute left there" is reachable from submit-application, review, and the delist cascade specifically. Also re-read §2.7 rule 36 to confirm the ladder text needs no change.
- (c) Adjustments made: scoped the illustrative list of prior recomputes to the three that can actually leave a value observable at authorize time for an `IN_REVIEW` vendor, and used "does not recompute it first" rather than any claim about what authorize *does* write (which is already stated in the following paragraph).

**Edit 3 — §3.5 complete-reauthorization does recompute**
- (a) Subject: the recompute that "against the current cycle" refers to, and which fields it moves.
- (b) Enumerated: `routes/vendors.py:199-228` (recompute sits *after* the state/training/open-case/hold/peer-group guards and immediately before the completeness test, so a request rejected earlier never recomputes); `services.py:52-54` (confirms both `accepted_submission_count` and `price_submission_complete` move, not just the boolean); `calc.py:67-81` `completeness_governing_cycle` (confirms "the governing cycle of §3.2" is the right referent, not "the current cycle" loosely); `routes/vendors.py:188-195` start-reauthorization (already documented at §3.5 as recomputing — left verbatim).
- (c) Adjustments made: named both recomputed fields instead of only the flag; anchored the recompute to "reaching that last check" so it inherits the ladder position rather than implying an unconditional recompute at request entry.

## Step 9: Complete PRD — 2026-09-01T12:32:00.000Z

Done. `PRD_COMPLETED.md` is written.

## Counts

| | |
|---|---|
| PRD_FINALIZED.md | 502 lines, 97,475 chars |
| PRD_COMPLETED.md | 502 lines, 104,044 chars (**+6,569**) |
| Lines touched | 36 (all 1:1 in-paragraph replacements; no new sections, no new paragraphs) |
| Ambiguity-pins | 37 |
| Mismatch-revisions | 4 |

## Changes

- §2.1 — insert — ambiguity — an empty `X-User-ID`/`X-User-Role` counts as absent (401) — `auth.py:31`
- §2.3 — insert — ambiguity — a non-integer `limit`/`offset` is also `ERR_INVALID_REQUEST` — `validators.py:161-176`
- §2.3 — insert — ambiguity — `created_at` ties everywhere break on creation sequence — `store.py:58-64`
- §2.3 — insert — ambiguity — list filters are exact string equality on identically-named params; unknown params ignored — `routes/common.py:29-38`
- §2.3 — insert — ambiguity — no list endpoint is vendor-scoped; a VendorOperator sees every row — `routes/price_submissions.py:77-88`, `routes/claims.py:85-96`
- §2.4 — insert — ambiguity — `version` is 1 on the row as first written — `store.py:37-48`
- §2.4 — revise — **mismatch** — a write landing on already-held values is not a mutation (no `updated_at`/`version` move) — `services.py:14-23`
- §2.5 — insert — ambiguity — clock response `data` is the single field `current_utc`; backwards moves allowed — `routes/ops.py:15-21`
- §2.6 — insert — ambiguity — non-integer values (`base_cents`, `cap_cents`, pcts, fractions) serialize as plain JSON numbers — `envelope.py:17-27`
- §2.7 r6 — insert — ambiguity — absent/null/non-string body FK is not resolved at rule 6, falls to rule 7 — `routes/common.py:18-26`
- §3.1 — insert — ambiguity — `max_monthly_redemption_cents` key required (explicit null for unbounded) — `routes/peer_groups.py:28-34`
- §3.1 — insert — ambiguity — retiring an already-`RETIRED` group is a no-op, version unmoved — `routes/peer_groups.py:83-85`
- §3.1 — insert — ambiguity — hop 4 visits each affected vendor once, ordered by its earliest voided submission — `services.py:126-132`
- §3.1 — insert — ambiguity — delisting an already-`DELISTED` item is a no-op; both actions return the acted-on resource — `routes/food.py:117-119`
- §3.2 — insert — ambiguity — `completed_at` accepted regardless of its relation to the clock — `routes/vendors.py:103`
- §3.2 — insert — ambiguity — with no governing cycle, `accepted_submission_count` is set to 0 — `calc.py:109-110`
- §3.3 — insert — ambiguity — `ACCEPT` leaves `review_reason` null, discarding any supplied reason — `routes/price_submissions.py:106`
- §3.4 — insert — ambiguity — pair sweep order: peer group `created_at` asc, then item `created_at` asc — `services.py:141-146`
- §3.5 — insert — ambiguity — a vendor with no `peer_group_id` fails with `ERR_PEER_GROUP_RETIRED` — `routes/vendors.py:144-146`
- §3.5 — insert — ambiguity — authorization clears `authorization_blocked_reason` to null — `routes/vendors.py:158`
- §3.5 — insert — ambiguity — null `reauthorization_due_at` → `ERR_REAUTH_WINDOW_NOT_OPEN` — `routes/vendors.py:186`
- §3.5 — insert — ambiguity — denial recomputes completeness after voiding (no delisting exception) — `services.py:101`
- §3.6 — insert — ambiguity — observation entry shape (explicit null `required_units`/`verdict`); response is the whole visit — `routes/monitoring.py:93-103`
- §3.6 — insert — ambiguity — `buy_items` entry validation, empty-list default, persisted on the visit and echoed — `routes/monitoring.py:112-129`, `services.py:224`
- §3.6 — insert — ambiguity — stock multiplier is exactly 1 when the vendor has no peer group — `calc.py:222-225`
- §3.6 — insert — ambiguity — server-created `MISSING` entries appended after recorded ones, in `code` order — `calc.py:236-247`
- §3.6 — insert — ambiguity — basket UPC resolution uses the §3.7 rule — `calc.py:275`
- §3.6 — insert — ambiguity — the cure condition gates only the `CURED` transitions; the vendor resets run regardless — `services.py:252-269`
- §3.6 — revise — **mismatch** — hop 2 fires at two **or more** uncured findings — `services.py:284`
- §3.7 — insert — ambiguity — line `upc` is any non-empty string; `quantity` >= 0 at intake (0 rejected later by `E03`) — `routes/claims.py:49-50`
- §3.7 — insert — ambiguity — a fresh claim carries `version` 1 (line_count/total written in the same act) — `routes/claims.py:72-74`
- §3.7 — revise — **mismatch** — UPC resolution prefers `ACTIVE`, else earliest-created `DELISTED`; `food_item_id` set even for a delisted match — `calc.py:300-312`
- §3.8 — insert — ambiguity — no participating lines → empty `line_recoupments`, `recoupment_cents` 0, still created — `calc.py:316-336`
- §3.9 — insert — ambiguity — `EPOCH` read with null `risk_epoch_at` returns null window/zero components/stored score; bad `basis` → 422 — `routes/vendors.py:67-87`
- §3.9 — insert — ambiguity — risk run refreshes `avg_monthly_redemption_cents` first; one epoch instant per run — `services.py:484-495`
- §3.9 — insert — ambiguity — manual `narrative` required; vendor `authorization_status` does not gate case open — `routes/sanctions.py:36,41-42`
- §3.9 — insert — ambiguity — system-opened case has null `narrative` and bypasses the open-case guard (two escalations → two cases) — `services.py:518-520`
- §3.9 — insert — ambiguity — imposition never answers `ERR_INVALID_VENDOR_STATE` — `routes/sanctions.py:114-129`
- §3.9 — insert — ambiguity — the disqualification cascade recomputes completeness after voiding — `services.py:479`
- §3.9 — insert — ambiguity — `cmp_payment_cents` optional (0 when omitted); ignored when closing from `DISQUALIFICATION_IMPOSED` — `routes/sanctions.py:159,174-175`
- §4 — revise — **mismatch** — monitoring visit added to the list of creates returning `201` — `routes/monitoring.py:59`
