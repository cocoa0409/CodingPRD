# Worklog — task_2578_correspondent_mortgage_purchase_seller_management

## Step 1: Create task directory — 2026-09-03T15:11:23.975Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2578_correspondent_mortgage_purchase_seller_management` and its `workspace/` subdirectory. Index 2578 was pre-assigned by the orchestrating invocation; no scan of `./tasks/` was performed (32 pipelines run concurrently on this host, auto-allocation would collide).

## Step 2: Generate scaffold — 2026-09-03T17:22:59.994Z

Scaffold generation for task 2578 is complete.

## Output (all under `/home/ubuntu/github/CodingPRD/tasks/task_2578_correspondent_mortgage_purchase_seller_management/`)

```
-rw-rw-r-- 1 ubuntu ubuntu 154978 SCAFFOLD.yaml                  3256 lines
-rw-rw-r-- 1 ubuntu ubuntu 113494 SCAFFOLD_DIFFICULTY_DESIGN.yaml 1852 lines
-rw-rw-r-- 1 ubuntu ubuntu 322537 SCAFFOLD_CORNER_DESIGN.yaml     5218 lines
```
(`worklog.md` and an empty `workspace/` were already present in the directory; untouched.)

## Lint verdict (verbatim, final run)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2578_correspondent_mortgage_purchase_seller_management/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2578_correspondent_mortgage_purchase_seller_management/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2578_correspondent_mortgage_purchase_seller_management/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    51
  §1.1 entities declared:     13
  §1.8 instances scanned:     18
  §1.9 instances scanned:     49
  Calls scanned (§1.8+§1.9):  1037

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Contents

- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys): 13 entities, 8 state machines (Loan/Commitment/Seller/FinancialStatement/QC/Defect/SuspenseCondition/Advice/Demand/EscrowTransfer/Scorecard family), 2 OCC rules, calculations (lock pricing with LLPA grid + clamps, purchase-advice net wire, pair-off fee dual variant, defect rate/scorecard grading, volume incentive), 67 priority-ordered validations, 51 endpoints, 66 errors, 6 roles with `segregation_of_duties`, `difficulty_level: expert_plus`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 9 sections × 2 depth instances (18 recipes).
- `SCAFFOLD_CORNER_DESIGN.yaml` — 49 instances across entities (10), state_machines (13), calculations (8), validations (16), endpoints (6), rbac (5), complexity_layers (5), consistency_model (1); 15 of them are `excluded_because` stubs deferring to a named depth instance (all cited names verified to exist), the other 34 carry full `test_recipe`s. Ends with an error-coverage matrix comment.

Verified invariants: no name collisions within or across the two design files; every non-stub instance has exactly the five allowed keys; all 66 catalog errors are triggered inside at least one real recipe (nothing covered only by prose); no forbidden concurrency vocabulary remains.

Two fixes were needed to reach a clean lint, both worth noting since they are scaffold-wide conventions:
1. Check (f) `FK_REVERSE_UNREACHABLE` fired on 9 FKs even though sub-resource GETs existed — the linter matches the literal segment `{id}` (`lint_fk_reverse_reachability` builds `f"{prefix}/{parent_seg}/{{id}}/"`). All 242 `{*_id}` path placeholders in `SCAFFOLD.yaml` (and 9 prose references in the corner file) were normalized to `{id}`.
2. Four captures used `$.data.net_wire_amount_cents`; the declared `PurchaseAdvice` field is `net_wire_cents`.

## Step 3: Copy shared files — 2026-09-03T17:23:15.499Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T17:41:00.000Z

PRD generation is complete.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2578_correspondent_mortgage_purchase_seller_management/workspace/PRD.md`

**File integrity (truncation guard):**
- Final size: **513 lines, 100,126 bytes**
- Last section heading: **`## 5. Error Code Catalogue`**
- The file ends at a real section boundary — the final line is the last row of the §5 table (`| ERR_MANDATORY_EXPOSURE_LIMIT_EXCEEDED | 409 |`), not mid-sentence. Written incrementally via one `Write` plus six `cat >> … << 'PRDEOF'` heredoc appends; no single-write cap was hit.

**Structure:** §1 Introduction; §2 with 10 subsections (2.1 RBAC, 2.2 response envelope, 2.3 pagination, 2.4 common properties + logical clock, 2.5 validation precedence, 2.6 money/rounding, 2.7 conserved quantities, 2.8 OCC, 2.9 segregation of duties, 2.10 cascades); §3 with 9 subsections (onboarding, approval/exposure/standing, product matrix + LLPA grid, lock desk pricing, commitment retirement, delivery + purchase review, clearing/rejection/purchase advice, repurchase + escrow, scorecards); §4 endpoint table with **51 rows × 4 columns**; §5 error table with **66 rows × 2 columns**. §2.2 is byte-identical to `section-2.2-response-structure.md`. Only two code fences exist in the document, both inside §2.2 — no pseudocode elsewhere, no fuzzy quantifiers.

**Hard Contract 1 — Field coverage check:**
```
- entities[].fields: 165 required, 165 present, 0 missing
- endpoints[].request_body: 62 required, 62 present, 0 missing
- endpoints[].query_params: 13 required, 13 present, 0 missing
Status: PASS
```

**Hard Contract 2 — Rule coverage check:**
```
- validations[] with priority: 66 checked, 66 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 54 checked, 54 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 66 checked, 66 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 51 checked, 51 expressed, 0 missing
- entities[].fields[] structured content: 165 checked, 165 reconstructible from prose, 0 missing
- sibling-branch symmetry: 13 groups checked, 13 with equal prose density, 0 asymmetric
Status: PASS
```
All 34 numeric constants from `calculations[].constants` appear verbatim (or in explicit words, e.g. -35 bps as "subtracts 35 basis points"), and all 88 declared enum values appear in backticks.

**Hard Contract 3 — Path purity check (§3 only):**
```
- backtick tokens scanned: 970
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```
(No §3 backtick token contains a `/` at all; endpoints are referred to only by state-transition framing, role+action verb, or capability description. Paths appear only in §2.8 for OCC and in the §4/§5 tables.)

**Notes / issues resolved during generation:**
- I did not open, grep, or reference `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`.
- I initially drafted 10 §3 subsections (over the 5–9 limit) and merged delivery with purchase review into §3.6, which also made the pre-existing forward cross-references (`§3.7` for fills, `§3.9` for scorecards) resolve correctly.
- I had invented an error ID `ERR_LOAN_NOT_CLEARED` for advice settlement; the scaffold declares no such error, so the gate is now expressed as structurally guaranteed by the `ERR_ADVICE_NOT_SETTLEABLE` state gate. A programmatic diff confirms the PRD names exactly the 66 declared error IDs and nothing else.
- The scaffold's validation priorities skip 65, so there are 66 validation rows (not 67); the ladder is reproduced faithfully in §2.5.

**Orchestrator verification:** independently ran `wc -l -c` (513 / 100126), `tail -12` and `grep -n '^## '`. The file's last line is the final `ERR_MANDATORY_EXPOSURE_LIMIT_EXCEEDED` table row of §5, the document's last section — confirmed NOT truncated, no regeneration needed.

## Step 5: Generate unit tests — 2026-09-03T19:07:07.766Z

Test generation for task 2578 is complete.

## Final file: `test_suite/test_15_corner_rbac_and_layers.py` (1072 lines, 17 tests)

Covers the last 8 queue-B instances: 5 `rbac`, 2 non-stub `complexity_layers` (OCC on delivery and on advice creation), 1 `consistency_model`. Classes: `TestEveryRoleActsWithinItsOwnMandate`, `TestCrossingIntoAnotherRolesExclusiveOperation`, `TestIdentityHeadersDecideBeforeAnythingElse`, `TestOneSellerReachingIntoAnothersFile`, `TestNobodyMayTakeBothHalvesOfASegregatedDecision`, `TestTheDeliveryVersionTokenMustBeFresh`, `TestTheAdviceVersionTokenMustBeFresh`, `TestOneResponseCarriesEveryConsequenceOfItsOwnMutation`.

## Verification passes (all clean)

- **Design-index coverage** (`Design:` tag reconciled against both yamls): 82 instances, 67 non-stub, **67/67 covered, 0 uncovered, 0 unknown tags, 0 stub instances translated**, every queue-A instance has >=2 tests. 117 test functions across 15 files (128 pytest cases; one 12-way parametrize in test_10).
- **PRD citations** (whitespace-normalized substring match against `workspace/PRD.md`): 117/117 tests have >=1 verbatim quote, exactly one trailing `Design:` line, 0 mismatches. Five fabricated quotes I initially wrote in test_15 were caught by this pass and replaced with real §2.8 / §3.7 / §3.4 sentences.
- **Hygiene**: no `scaffold`/`§1.x` references, no `skip`/`xfail`/`skipif` anywhere; `pyflakes` and `py_compile` clean on all test files; `pytest --collect-only` imports and collects everything.

## PRD-first corrections applied to design slips (asserted the PRD-derived value, noted in the docstrings)

- SoD instance claimed the blocked seller is still `APPLIED`; PRD §3.2 says opening the first QC review advances it to `UNDER_REVIEW` — asserted `UNDER_REVIEW`.
- consistency_model instance claimed `net_funded == 40377389` and `exposure == 60000000` for a RELEASED loan on a partially filled line; PRD uniquely derives **41,127,389** (escrow 250,000 + SRP 500,000 added) and **100,000,000** (exposure falls only at a terminal commitment status) — asserted those.
- Undeclared defect categories `UNDERWRITING`/`PROPERTY` in the design substituted with declared ones (`CREDIT`/`INCOME`/`COLLATERAL`).

## Earlier fix worth flagging

`test_helpers/api_errors.py` had all 66 `ApiErrorId` members declared without the `ERR_` prefix while every test references `ApiErrorId.ERR_*` — a runtime `AttributeError` invisible to `py_compile`. Renamed so member name == value; all references now resolve.

## Listings

`test_helpers/` — 9 files, 3000 lines (`__init__` 148, `api_client` 436, `api_errors` 172, `assertions` 423, `constants` 129, `factories` 284, `fixtures` 815, `test_users` 121, `types` 472).
`test_suite/` — `conftest.py` 51 + 15 test files: 254, 229, 201, 220, 195, 170, 217, 206, 229, 539, 785, 672, 946, 759, 1072. Total across both dirs: 9745 lines. Both directories sit at the task root; `workspace/` contains only `INSTRUCTION.md`, `PRD.md`, `implementation/` (never read or written).

**Orchestrator verification:** confirmed `test_helpers/` and `test_suite/` are at the task root and that `workspace/` holds only `INSTRUCTION.md`, `PRD.md`, `implementation/` — no misplaced test directories to move before Step 7.

## Step 6: Generate implementation — 2026-09-03T19:07:07.766Z

Both smoke suites pass clean and one real spec bug was found and fixed on the second pass.

## Bug found and fixed

`workspace/implementation/routes/loans.py` — the state gates on defect and suspense-condition creation were too narrow. They admitted only `IN_REVIEW` / `SUSPENDED` (+ `PURCHASED` for defects), so the `CLEARED_FOR_PURCHASE -> SUSPENDED` cascade was unreachable and `PurchaseAdvice.VOIDED` was dead code.

SCAFFOLD.yaml line 2098 (the `ERR_INVALID_LOAN_STATE` check text) and the PRD's "Any other purchase status is refused" sentence both omit `CLEARED_FOR_PURCHASE`, but four other places require it: the Loan state machine (SCAFFOLD 1244-1251), the PurchaseAdvice `ISSUED -> VOIDED` transition (1421-1422), both endpoint `side_effects` blocks (2677, 2723), and PRD line 264 ("a late finding cannot leave a priced advice standing"). I resolved it in favour of the cascade — the narrow reading makes a documented status and transition unreachable. New constants:

```python
CONDITIONABLE_STATES = ("IN_REVIEW", "SUSPENDED", "CLEARED_FOR_PURCHASE")
DEFECTABLE_STATES = CONDITIONABLE_STATES + ("PURCHASED",)
```

`helpers.on_review_item_added` already implemented the void cascade correctly, so no change was needed there. `DELIVERED`, `REJECTED`, `REPURCHASE_DEMANDED` and `REPURCHASED` still return `ERR_INVALID_LOAN_STATE`.

## Verification

- Suite 1 (`/tmp/smoke_2578.py`, 60 calls): onboarding -> lock -> deliver -> review/defect/cure/clear -> advice+settle -> escrow -> EPD demand/appeal/uphold/settle -> pair-off -> expiry sweep -> pagination + 401/403/404/400. **FAILURES: 0** (re-run after the fix; no regression).
- Suite 2 (`/tmp/smoke2_2578.py`, 38 calls): CONDITIONAL tier + `servicing_retained_eligible=false`, non-curable path (`ERR_DEFECT_NOT_CURABLE`, group-9 clear gate, reject compensation restoring `allocated=0 / available=100,000,000` with status still `LOCKED`), `expire-conditions` strict-deadline sweep, advice SUPERSEDED/VOIDED chain, per-defect independent rounding (expired -50bps + waived -25bps = -375,000), scorecard `UNRATED` below `MIN_SCORED_LOANS`, `ERR_SCORECARD_PERIOD_OVERLAP` / `_NOT_ENDED`, and WATCH->SUSPEND->TERMINATE (manual suspension cancels nothing; termination cancels the open line with the 25,000 `ADMINISTRATIVE_FLAT` fee). **FAILURES: 0**.
- Endpoint surface re-diffed against SCAFFOLD.yaml: 51 scaffold endpoints, 51 matched, no missing, no extra.
- Smoke server was killed by exact PID each time (`kill $(cat /tmp/smoke2_2578.pid)`); no pattern kill was ever used. Nothing is left running and `__pycache__` dirs were removed.

## Final listing

`/home/ubuntu/github/CodingPRD/tasks/task_2578_correspondent_mortgage_purchase_seller_management/workspace/implementation/`

```
-rwxrwxr-x   398  start.sh            (10 lines, executable)
-rw-rw-r--    11  requirements.txt     (1)
-rw-rw-r--  1869  app.py              (59)
-rw-rw-r--  1731  auth.py             (68)
-rw-rw-r-- 14455  calc.py            (410)
-rw-rw-r--  1194  envelope.py         (57)
-rw-rw-r--  8215  errors.py          (152)
-rw-rw-r--  7093  helpers.py         (235)
-rw-rw-r--  4881  store.py           (197)
-rw-rw-r--  6125  validate.py        (191)
routes/
-rw-rw-r--    24  __init__.py          (1)
-rw-rw-r--  5577  catalog.py         (139)
-rw-rw-r-- 13957  commitments.py     (340)
-rw-rw-r-- 18178  loans.py           (515)
-rw-rw-r-- 10573  repurchase.py      (287)
-rw-rw-r-- 16802  sellers.py         (436)
                          total 3098 lines
```

## Step 7: Run tests and iterate — 2026-09-03T19:35:33.368Z

All 8 parallel rounds now pass 128/128.

## Summary

**Iterations run:** 3 sweeps total (1 baseline 8-round sweep at 93/128, 2 private full serial rounds for diagnosis, 1 final 8-round sweep at 128/128). Zero flakiness observed at any point — all 8 rounds were byte-identical in pass/fail set every time, so no failure was load-induced.

**Tests deleted:** none. One assertion removed under STEP 1c partial coverage (see below).

**Fixes applied to `test_suite/`**

- `test_suite/*.py` (10 files, 32 assertions) — STEP 2, assertion layer. Bare-`Z` timestamp equality assertions (`== "2026-08-01T00:00:00Z"`) rewritten to three-fractional-digit form (`== "...T00:00:00.000Z"`). PRD §2.4 verbatim: "`created_at` (string): an ISO 8601 UTC timestamp with **exactly three fractional digits** (for example `2026-08-01T00:00:00.000Z`)" and "All thirteen resource types carry all four properties". The implementation was already correct; the assertions were unfaithful. Fields touched: `created_at`, `delivered_at`, `purchased_at`, `completed_at`, `cured_at`, `cleared_at`, `settled_at`, `satisfied_at`, `closed_at`, `cure_deadline_at`, `due_at`, `transfer_due_at`, `appeal_deadline_at`. `fixtures.setup_clock(...)` *inputs* left untouched.
- `test_suite/test_12_corner_calculations.py:339` — STEP 2, assertion layer. `validate_error(..., ERR_SERVICING_RETAINED_NOT_ELIGIBLE, 409)` -> `422`. PRD §2.5 verbatim: "**Product-matrix referential gates**, in this relative order: `ERR_PRODUCT_NOT_ELIGIBLE`, `ERR_COMMITMENT_TYPE_NOT_ALLOWED`, `ERR_SERVICING_RETAINED_NOT_ELIGIBLE`. All three are HTTP 422." plus the §5 status table row `| ERR_SERVICING_RETAINED_NOT_ELIGIBLE | 422 |`. The exact `error_id` assertion was kept; only the wrong status number was corrected.
- `test_suite/test_13_corner_validations.py:131-135` — STEP 2, **fixture/setup layer**. The test's second commitment was locked with `delivery_window_start="2026-08-31"`/`delivery_expiry_date="2026-09-30"` while the logical clock sat at `2026-08-01`, i.e. outside its own half-open delivery window, so the PRD-faithful implementation correctly answered `ERR_COMMITMENT_EXPIRED` (ladder level 11, temporal windows) before ever reaching `ERR_DUPLICATE_SELLER_LOAN_NUMBER` (level 12, uniqueness). Replaced the out-of-window dates with `commitment_type="BEST_EFFORTS"` on the default `2026-08-01`->`2026-08-31` window: still "a different line of the same seller" (the test's stated intent), now clock-valid, and PRD §3.4 exempts `BEST_EFFORTS` from the mandatory delivery-window-overlap rule in both directions. No implementation check was weakened.
- `test_suite/test_14_corner_endpoints.py:177` — **STEP 1c PARTIAL COVERAGE / BRANCH-ASYMMETRIC SIDE EFFECT.** Removed `assert unchanged["version"] == version_after_sweep` (and its now-unused capture) from `test_the_sweep_expires_only_the_strictly_overdue_items_and_then_idles`. Every other assertion in the test is verbatim-covered and was kept. PRD §3.6 describes the condition sweep only on the branch where items expire: "The loan's `open_defect_count` and `open_suspense_count` fall by the number of items expired in each family, each affected child's `version` increments by 1, and the loan's `version` increments by 1." PRD never states what a sweep that expires *nothing* does to the loan row, and the sentence admits two articulable implementations — the "affected" qualifier applies to children only, so a reader may take the loan's bump as unconditional for the endpoint, while §2.4's "increments by exactly 1 on **every mutation** of that resource" supports no bump on a no-op. Scaffold rule that drove generation: `Corner/endpoints/late_cure_and_late_clearance_are_refused_then_the_loan_sweep_expires_both_items`.

**Fixes applied to `test_helpers/`**

- `test_helpers/assertions.py:163`, `assert_commitment()` — **STEP 1a PRD SILENCE / COMPUTED-FIELD SILENCE.** Removed `assert isinstance(data["lock_term_bps"], int)`. This single shared-helper line was raising `KeyError: 'lock_term_bps'` in **9** otherwise-legitimate tests (the whole pricing/exposure/pair-off cluster). PRD §3.4 names exactly which pricing intermediates are persisted: "`lock_term_days` is derived ... and is stored on the commitment" and "The second input is the **adjustment grid**, whose contribution is stored as `llpa_bps_applied`". For the lock-term tier PRD says only that the tabled term "contributes 0 basis points / -12 / -25 / -40" — the contribution appears solely inside the pricing formula and is never named as a response-visible commitment attribute, so a PRD-only implementer has no basis for exposing `lock_term_bps`. Adding the field to `implementation/` was ruled out by the cardinal rule against untraceable response fields. `lock_term_days` and `llpa_bps_applied` assertions were both retained.

**Fixes applied to `implementation/`:** none. No implementation defect was found; every failure traced to an unfaithful test assertion, an out-of-window test fixture, or a PRD-silent shared helper assertion.

**Final sweep — `ls -la workspace/implementation/results.*.json` confirms all 8 files present (Sep 3 19:34):**

| round | passed / total |
|---|---|
| results.1.json | 128 / 128 |
| results.2.json | 128 / 128 |
| results.3.json | 128 / 128 |
| results.4.json | 128 / 128 |
| results.5.json | 128 / 128 |
| results.6.json | 128 / 128 |
| results.7.json | 128 / 128 |
| results.8.json | 128 / 128 |

`failed=0, errors=0, skipped=0` in every round; union of failing tests across all 8 rounds is empty. Round durations 291-295 s.

**Orchestrator verification (independent):** `ls -la workspace/implementation/results.*.json` shows all 8 files present (44,271-44,283 bytes each, Sep 3 19:34), and a fresh JSON parse of each confirms `passed=128 total=128 failed=0 errors=0 skipped=0` for all 8 rounds. The clean sweep is backed by artifacts on disk, not by the subagent's claim alone.

**Step 8 decision:** NOT skipped. Step 7 applied 0 implementation fixes but made 4 `test_suite/` fixes plus 1 `test_helpers/` fix and removed 2 assertions under PRD-silence findings, so the skip condition (0 deletions AND 0 test_suite fixes AND 0 test_helpers fixes AND 0 implementation fixes) does not hold. The two PRD-silence findings (`lock_term_bps` not being a response-visible commitment attribute; the no-op condition-sweep branch's effect on the loan `version`) are exactly the kind of unpinned behavior Step 8 exists to pin.

## Step 8: Finalize PRD — 2026-09-03T19:39:56.843Z

PRD_FINALIZED.md is written.

## Counts
- PRD.md: 513 lines / 100,126 bytes. PRD_FINALIZED.md: 513 lines / 100,991 bytes -> 0 line delta (+0.00%), +865 bytes (+0.86%). Three in-place sentence extensions, no new sections.
- `tail -5` confirms the file ends at the last row of the §5 error table (`| ERR_MANDATORY_EXPOSURE_LIMIT_EXCEEDED | 409 |`).

## Changes (3)
- **§2.4 (line 100) — insert** — added a sentence pinning that *every* instant-valued field the server writes, including deadlines derived by advancing the clock (`cure_deadline_at`, `due_at`, `transfer_due_at`, `appeal_deadline_at`), renders in the same three-fractional-digit ISO 8601 UTC form when non-null — `implementation/store.py:59-66` (`fmt_dt`), `implementation/helpers.py:226-228` (`datetime_field`).
- **§3.4 (line 220) — insert** — added that the lock-term tier's basis-point contribution is not a persisted commitment field (only the grid's `llpa_bps_applied` is), so the tier is observable only via `lock_term_days` and the price — `implementation/routes/commitments.py:97-121` (record has `lock_term_days`, `llpa_bps_applied`, no `lock_term_bps`), `implementation/calc.py:135-144`.
- **§3.6 (line 276) — revise** — the loan's `version` increment on the condition sweep is now stated as exactly 1 **on every run, including a run that expires nothing** (`updated_at` refreshes either way) — `implementation/routes/loans.py:298-300` -> `implementation/helpers.py:205-212` (`on_review_item_resolved` calls `touch(loan)` unconditionally), `implementation/store.py:156-171`.

Not patched (Step 7 items that were not PRD gaps): the `ERR_SERVICING_RETAINED_NOT_ELIGIBLE` 409->422 assertion fix (PRD §2.5 + §5 already say 422); the `test_13` out-of-window commitment fixture (pure fixture bug, impl matches PRD ladder at `routes/commitments.py:293-303`); the bare-`Z` equality rewrites on fields PRD already formats (`created_at`/`updated_at`) — covered generically by the §2.4 edit.

## Pre-edit search log
**Edit 1 (§2.4 timestamp rendering)**
- (a) Subject: rendering format of every instant-valued persisted field, and where instants vs. calendar dates are stored.
- (b) Enumerated/read: `store.fmt_dt` (the only formatter, always `%03d` milliseconds, returns `None` for `None`); `store.base_record` (`created_at`/`updated_at`); `store.touch`; `envelope.py:20` (`api_request_timestamp`); every `datetime_field` callsite — `routes/loans.py:113,163,217,255,401,453,458,472`, `routes/repurchase.py:87,218,285`, `routes/commitments.py:333`, `routes/sellers.py:234,415`; calendar-date fields stored as client strings via `validate.req_date` (`fiscal_year_end`, `closing_date`, `first_payment_due_date`, `delivery_window_start`, `delivery_expiry_date`, `period_start`, `period_end`).
- (c) Adjustment: scoped the claim to "instant-valued field" so the date-typed fields (kept as `YYYY-MM-DD`) are not swept in, and added "whenever it is non-null" because `cure_deadline_at` is `None` for `NON_CURABLE` defects and `cured_at`/`cleared_at`/`settled_at`/`completed_at`/`satisfied_at`/`closed_at`/`purchased_at` start null.

**Edit 2 (§3.4 lock-term contribution not persisted)**
- (a) Subject: the commitment record's persisted/response field set, specifically pricing intermediates.
- (b) Enumerated/read: `routes/commitments.py:97-121` (full creation dict), `calc.commitment_price_pct`/`lock_term_bps` (term bps returned but only used in the formula), `store.public` (serializes every non-underscore key, so persisted == response), and every later writer of commitment fields — `routes/commitments.py:185-190` (pair-off), `helpers.assess_administrative_flat` (expiry/cancellation), `routes/loans.py:477-491` (fill/tolerance write-off), `routes/loans.py:352-357` (rejection compensation): none introduces a lock-term bps field.
- (c) Adjustment: first draft said "of the three pricing inputs only `lock_term_days` and `llpa_bps_applied` are stored", which would have implied `commitment_type` is not stored (it is, and it is a documented list filter and the pair-off variant selector). Reworded to "of the three basis-point contributions only the adjustment grid's `llpa_bps_applied` is stored".

**Edit 3 (§3.6 sweep bumps the loan version unconditionally)**
- (a) Subject: loan-row mutation semantics of the condition sweep, and the shared resolution cascade.
- (b) Enumerated/read: `routes/loans.py:268-306` (sweep always calls `on_review_item_resolved`), `helpers.on_review_item_resolved` (unconditional `touch(loan)`; the `SUSPENDED -> IN_REVIEW` + `review_cycle_count` branch is conditional), its other callers `cure_defect` (`loans.py:167`), `waive_defect` (`loans.py:189`), `clear_condition` (`loans.py:260`), plus `store.touch`'s per-request/per-record dedupe (so multiple expired children still bump the loan exactly once), and the parallel commitment sweep `routes/commitments.py:205-236` (touches only selected commitments — deliberately left undescribed by this edit).
- (c) Adjustment: dropped a first draft that also asserted a no-op run "leaves its counters, `purchase_status` and `review_cycle_count` alone" — `on_review_item_resolved` still evaluates the cure-cycle branch on a no-op run, so that universal claim could contradict the shared-cascade paragraph; the committed wording constrains only `version`/`updated_at`.

**Orchestrator verification:** `wc -l -c` gives PRD.md 513/100126 and PRD_FINALIZED.md 513/100991; an md5 comparison confirms the two files are NOT byte-identical (i.e. the pass really edited), and `tail -3` confirms PRD_FINALIZED.md still ends on the final §5 error-table row.

## Step 9: Complete PRD — 2026-09-03T20:00:50.211Z

Run as **three sequential file-partitioned passes** over `implementation/` rather than one monolithic scan, so no single subagent had to hold all 3,098 lines of implementation plus the 513-line PRD in context (a single-pass scan risks producing a PRD_COMPLETED.md byte-identical to its source, i.e. a scan that never really ran). Each pass edited the same `workspace/PRD_COMPLETED.md` in place with the Edit tool; pass 1 created it from `PRD_FINALIZED.md`, passes 2 and 3 were explicitly forbidden to re-copy it or revert earlier passes' edits.

Partition:
- Pass 1 — `app.py`, `auth.py`, `envelope.py`, `store.py`, `validate.py`, `errors.py`, `routes/catalog.py`, `routes/sellers.py` (1,299 lines)
- Pass 2 — `calc.py`, `helpers.py`, `routes/commitments.py` (985 lines)
- Pass 3 — `routes/loans.py`, `routes/repurchase.py` (802 lines)

### Pass 1 (envelope, auth/RBAC, store, shared validation, error table, catalogue, seller lifecycle)

- Source 513 lines / 100,991 chars -> 513 lines / **105,413 chars** (+4,422). 22 line-level edits, all in-paragraph; no new sections, no rows added to §5.
- Counts: **21 ambiguity-pins, 1 mismatch-revision.**
- §2.1 — revise — ambiguity — whitespace-only `X-User-ID`/`X-User-Role` counts as empty (401); both values trimmed before role match / id compare — auth.py:25-30
- §2.2 — revise — ambiguity — `api_request_id` is `req_` plus exactly twenty uppercase-alphanumeric characters — envelope.py:10-14
- §2.3 — revise — ambiguity — non-integer `limit`/`offset`, `limit` outside 1-100, negative `offset` -> `ERR_INVALID_REQUEST`; empty-string param treated as omitted — validate.py:160-179
- §2.3 — revise — ambiguity — `created_at` ties broken by insertion order (earliest first) — store.py:174-176
- §2.3 — revise — ambiguity — `has_more` = `offset` + items-on-page < `total_count` — envelope.py:42
- §2.3 — revise — ambiguity — filters matched literally, never enum-validated (unknown value => empty page, not an error); empty-string filter and unknown query params ignored — validate.py:187-191, routes/sellers.py:88-91
- §2.4 — revise — **mismatch** — a row reached several times in one request advances `version` by exactly 1 total, not once per cascade effect — store.py:156-171
- §2.4 — revise — ambiguity — `current_utc` accepts `Z` or numeric offset, zone-less read as UTC, unparseable => `ERR_INVALID_REQUEST`; clock may move backwards; call answers 200 with empty `data` — store.py:69-84, routes/catalog.py:23-29
- §2.5 (group 4) — revise — ambiguity — absent/empty/unparseable body read as `{}`; non-object body => `ERR_INVALID_REQUEST`; JSON `null` counts as absent — validate.py:17-35
- §2.6 — revise — ambiguity — `_pct` may be supplied as an integer; percentages returned as JSON numbers (100.000 => `100.0`) — validate.py:68-85, store.py:179-193
- §3.1 — revise — ambiguity — whitespace-only `legal_name` rejected as empty — routes/sellers.py:37-39
- §3.1 — revise — ambiguity — statement `review_note` capped at 1,000 chars; null when omitted — routes/sellers.py:111
- §3.1 — revise — ambiguity — on review, supplied `review_note` overwrites the submitted note, omitted note leaves it untouched (not cleared) — routes/sellers.py:160-161
- §3.2 — revise — ambiguity — approval `review_note` capped at 1,000 chars and not persisted on the seller — routes/sellers.py:249
- §3.2 — revise — ambiguity — SoD also outranks the `UNDER_REVIEW` state gate and is evaluated identically for `DECLINE` — routes/sellers.py:251-259
- §3.2 — revise — ambiguity — standing-action `note` capped at 1,000 chars and not persisted — routes/sellers.py:308
- §3.2 — revise — ambiguity — `TERMINATE` neither sets nor clears `suspension_reason` — routes/sellers.py:329-335
- §3.3 — revise — ambiguity — `product_code` uniqueness holds regardless of `status`; lowercase letter => `ERR_INVALID_REQUEST`; `description` <= 500 chars — routes/catalog.py:40-58
- §3.3 — revise — ambiguity — empty / undeclared-member / duplicate-member arrays => `ERR_INVALID_REQUEST`, stored in supplied order — validate.py:134-147
- §3.3 — revise — ambiguity — `adjustment_code` uniqueness within product holds regardless of `status` — routes/catalog.py:108-111
- §3.9 — revise — ambiguity — opening a scorecard is gated on nothing else (any `approval_status` / `delivery_standing`) — routes/sellers.py:345-360
- §3.9 — revise — ambiguity — `RECOVERED` leaves `suspension_reason` untouched (only manual `REINSTATE` clears it) — routes/sellers.py:430-432
- §4 preamble — revise — ambiguity — trailing slash equivalent; unrouted path => `ERR_NOT_FOUND` 404, bad method => `ERR_METHOD_NOT_ALLOWED` 405, both outside the §5 catalogue — app.py:23, app.py:35-44, errors.py:79-80
- Also verified programmatically: every `error_id` -> HTTP status in `errors.ERROR_HTTP` matches the §5 table exactly (66/66); the only extras are the two routing errors pinned in §4, and every error id has a default message.

### Pass 2 (calculations, constants, rounding/clamps, cascade helpers, commitment & lock-desk surface)

- 513 lines / 105,413 chars -> 513 lines / **107,743 chars** (+2,330). All edits in-paragraph.
- Counts: **8 ambiguity-pins, 1 mismatch-revision.**
- §2.6 — insert — mismatch — the decimal-place rule constrains only server-computed percentages; client-supplied `_pct` values (`reference_ltv_pct`, `pair_off_market_price_pct`, `note_rate_pct`, `ltv_pct`) are stored/echoed verbatim and consumed at full supplied precision, never re-rounded — validate.py:68-85 + routes/commitments.py:106,187,318
- §2.3 — insert — ambiguity — a `SellerUser` has any `seller_id` filter forced to its own `X-User-ID` (omission narrows rather than exposes all; a foreign value is `ERR_SELLER_SCOPE_VIOLATION`), checked after `limit`/`offset` validation — routes/commitments.py:135-136, auth.py:62-68
- §2.8 — revise — ambiguity — `expected_commitment_version`/`expected_loan_version` below 1 or non-integer is `ERR_INVALID_REQUEST`, not the 412 stale error — routes/commitments.py:248
- §3.4 — insert — ambiguity — both commitment date cross-field failures (expiry <= start; span > 60 days) are `ERR_INVALID_REQUEST`; neither date is compared to the logical clock, so a wholly-past window locks fine and is immediately sweep-eligible — routes/commitments.py:50-55
- §3.5 — insert — ambiguity — `pair_off_market_price_pct` is mandatory, >= 0, with no upper bound; negative or omitted is `ERR_INVALID_REQUEST`, and a price above the §3.4 ceiling is accepted (drives market loss to zero) — routes/commitments.py:172-173, calc.py:166-171
- §3.5 — insert — ambiguity — the expiry sweep's `seller_id` may arrive in the body **or** as a query parameter (body wins), must resolve to a live seller else `ERR_INVALID_REQUEST`, and omission sweeps all sellers — routes/commitments.py:209-213
- §3.6 — insert — ambiguity — `first_payment_due_date` <= `closing_date` is `ERR_INVALID_REQUEST` — routes/commitments.py:263-264
- §3.6 — insert — ambiguity — `seller_loan_number` uniqueness spans every `purchase_status`, so a number consumed by a later-`REJECTED`/`REPURCHASED` loan still blocks reuse — routes/commitments.py:300-303
- §3.6 — insert — ambiguity — delivery never changes the commitment's `status`, even when it consumes all remaining capacity (a `LOCKED` line stays `LOCKED` at zero available) — routes/commitments.py:336-338
- No change needed for the rest of `calc.py`/`helpers.py`: lock-term bps table incl. the sub-15-day 0-bps floor, LLPA band inclusivity/sum-over-all-matches, clamp-before-round at 98.000/104.000, +-25/-35 type spread, floored 2.00% tolerance, billable-shortfall/25,000-cent admin fee and all three `pair_off_method` variants, volume tiers 0/5/10 with the loan-under-advice exclusion, per-component and per-defect advice rounding with 360-day accrual and the -50 bps expired-defect penalty, defect classification and 15/10/5 + 7-day windows, QC outcome ladder, 10x/5x net-worth multiplier vs the 5,000,000,000-cent cap, defect-rate/grade/breach thresholds and the standing-action ladder, the governing-statement/review selectors, `recompute_available`, `release_exposure`, `assess_administrative_flat`, `cancel_open_commitments`, and both review-cascade helpers.

### Pass 3 (purchase-review surface, purchase advice, repurchase, escrow transfer)

- 513 lines / 107,743 chars -> 513 lines / **111,312 chars** (+3,569). All edits in-paragraph.
- Counts: **18 ambiguity-pins, 4 mismatch-revisions.**
- §3.6 (open review) — insert — ambiguity — `note` <= 1,000 chars, schema-checked but not persisted — loans.py:70
- §3.6 (defects) — revise — **mismatch** — allowed states now include `CLEARED_FOR_PURCHASE` (PRD listed only IN_REVIEW/SUSPENDED/PURCHASED yet later described the cleared->suspended cascade); refused set enumerated — loans.py:26,94
- §3.6 (suspense conditions) — revise — **mismatch** — allowed states are IN_REVIEW/SUSPENDED/**CLEARED_FOR_PURCHASE** and explicitly not PURCHASED (PRD said "IN_REVIEW or SUSPENDED only"); `description` <= 1,000 chars — loans.py:25,203,205
- §3.6 (four resolutions) — insert — ambiguity — none of cure/waive/clear/sweep gates on the loan's `purchase_status`; cascade only moves a `SUSPENDED` loan — loans.py:150-167,178-189,248-260,270-300
- §3.6 (cure) — insert — ambiguity — `cure_document_reference` 1-200 chars — loans.py:147
- §3.6 (waiver) — insert — ambiguity — a waiver is not bounded by the cure window; `ERR_CURE_WINDOW_EXPIRED` never arises on that path — loans.py:176-181
- §3.6 (clearance) — insert — ambiguity — `document_reference` 1-200 chars — loans.py:246
- §3.7 (clearing) — insert — ambiguity — `note` <= 1,000 chars, not persisted — loans.py:318
- §3.7 (rejection) — insert — ambiguity — `note` <= 1,000 chars, not persisted — loans.py:341
- §3.7 (advice creation) — insert — ambiguity — `funding_reference`, `settled_by_user_id`, `settled_at` start null — loans.py:394-398
- §3.7 (settlement) — insert — ambiguity — `funding_reference` 1-200 chars — loans.py:436
- §3.7 (settlement) — insert — ambiguity — SoD (group 6) is evaluated before the advice-status gate (group 8), so the issuer gets `ERR_SEGREGATION_OF_DUTIES` even on a non-`ISSUED` advice — loans.py:439-443
- §3.7 (escrow transfer creation) — insert — ambiguity — `goodbye_letter_reference`, `completed_at`, `reversal_reason` start null — loans.py:466-471
- §3.7 (commitment fill) — insert — ambiguity — a further fill on an already-`FULFILLED` line repeats the moves, re-fires the mandatory exposure release, and `open_mandatory_exposure_cents` is floored at zero — loans.py:481-491 (via helpers.release_exposure)
- §3.7 (payment events) — revise — **mismatch** — endpoint is ungated on `purchase_status` (PRD's "once a loan is purchased" implied a gate that does not exist) — loans.py:505-514
- §3.8 (defect evidence) — revise — **mismatch** — a `source_defect_id` resolving to no defect is `ERR_INVALID_REQUEST` (group 4, ahead of the loan-state gate), not `ERR_DEFECT_EVIDENCE_REQUIRED` — repurchase.py:41-43
- §3.8 (EPD demand) — insert — ambiguity — supplying `source_defect_id` on an EPD demand is `ERR_INVALID_REQUEST` ahead of all state/window gates; the 120-day window runs from `first_payment_due_date` at midnight UTC and the instant exactly 120 days later is still inside — repurchase.py:39-40,52-56
- §3.8 (demand creation) — insert — ambiguity — `appeal_reason`, `remittance_reference`, `decided_by_user_id`, `satisfied_at` start null — repurchase.py:77-86
- §3.8 (appeal) — insert — ambiguity — `appeal_reason` 1-2,000 chars — repurchase.py:153
- §3.8 (decision) — insert — ambiguity — `note` <= 1,000 chars, not persisted; SoD precedes both branches' status gates — repurchase.py:174-178
- §3.8 (satisfaction) — insert — ambiguity — `remittance_reference` 1-200 chars — repurchase.py:207
- §3.8 (escrow completion) — insert — ambiguity — `goodbye_letter_reference` 1-200 chars — repurchase.py:270
- Checked and already uniquely pinned: all role sets in the §4 table match the `@endpoint` decorators exactly for all 26 endpoints in this partition; loan/defect/condition/advice/demand/transfer list filters and `_seq` ordering; classification and cure-window derivation; sweep semantics incl. the unconditional loan `version` bump and its 3-field response; clear/reject gate ordering and the rejection compensation leaving commitment status untouched; `expected_loan_version` precedence over the state gate; volume-incentive month-to-date window and exclusion of the loan under advice; all per-component advice amounts; the full satisfaction unwind (advice `REVERSED`, transfers `REVERSED` with `REPURCHASE_SATISFIED`, seller cash/fee moves, commitment untouched); transfer completion gate order (`NOT_PENDING` -> `LOAN_UNDER_REPURCHASE` -> `OVERDUE`).

### Step 9 totals and orchestrator verification

- 53 edits total across the three passes: **47 ambiguity-pins, 6 mismatch-revisions.**
- `PRD.md` 513 / 100,126 -> `PRD_FINALIZED.md` 513 / 100,991 -> `PRD_COMPLETED.md` 513 / **111,312** (+11,186 chars over PRD.md, +11.2%; line count unchanged because every edit is in-paragraph).
- `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` — the scan genuinely ran. `tail -3` confirms it still ends on the final §5 error-table row and `grep -c '^## '` still finds all 5 top-level sections.
- `find workspace/implementation -newer results.8.json` returns nothing: **no implementation file was modified during Steps 8 or 9**, so the verified 8x128/128 sweep from Step 7 remains valid for the delivered implementation. Steps 8 and 9 touched documentation only.

Pipeline complete: Step 9 has written `workspace/PRD_COMPLETED.md`.
