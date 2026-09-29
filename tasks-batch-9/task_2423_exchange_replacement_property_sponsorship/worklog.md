# Worklog — task_2423_exchange_replacement_property_sponsorship

## Step 1: Create task directory — 2026-09-02T15:56:59.839Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2423_exchange_replacement_property_sponsorship` and its `workspace/` subdirectory. Index 2423 was pre-assigned by the invoking pipeline (no ./tasks/ scan performed, per instruction — concurrent pipelines on this host).

## Step 2: Generate scaffold — 2026-09-02T17:36:06.459Z

All three artifacts are complete and lint-clean.

**Lint verdict (verbatim, final run):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2423_exchange_replacement_property_sponsorship/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2423_exchange_replacement_property_sponsorship/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2423_exchange_replacement_property_sponsorship/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    78
  §1.1 entities declared:     16
  §1.8 instances scanned:     18
  §1.9 instances scanned:     77
  Calls scanned (§1.8+§1.9):  1889

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2423_exchange_replacement_property_sponsorship/`)
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys), 3,401 lines
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`, 3,779 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`, 13,494 lines

**SCAFFOLD.yaml content** — difficulty_level `expert_plus`; archetypes Compliance/audit + Temporal windowing; layers dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers; topology graph; state_machine_shape parallel; role_model segregation_of_duties; consistency immediate.
- **16 entities**: Property, DstTrust, Offering, Investor, ExchangeFile, PropertyIdentification, Subscription, LoanFacility, MasterLease, TrustLedgerEntry, CapitalNeed, Distribution, DistributionAllocation, TaxStatement, ExitEvent, ExitConsent
- **13 state machines** (Offering cyclic DRAFT↔UNDER_REVIEW, Investor parallel accreditation × suitability, DstTrust posture as derived aggregate), **2 OCC rules** (Offering.version on `POST /subscriptions`, DstTrust.version on `POST /distributions`)
- **21 calculations** (3 dual-variant: distribution distributable, tax allocation, exit net proceeds), **62 ordered validations**, **78 endpoints**, **76 error codes**, **7 roles** (Investor `entity_backed:Investor`, others opaque); mandatory logical clock defaulting to 2026-08-01T00:00:00Z

**§1.8 depth probe** — 9 Difficulty Rules × 2 differentiated instances = **18 instances**, e.g. provisional-vs-final distribution divergence, units-at-year-end vs unit-days-weighted tax allocation, capital-stack gross-up evaluation order, round-then-residual-sweep allocation, PPM revision cycle, 45-day inclusive boundary, LTV exactly at 75%, half-open distribution periods vs closed-interval lease overlap, unit/cash conservation on rescission and capex void.

**§1.9 breadth probe** — **93 instances** across the guide's nine sections (**77 with full test recipes**, **16 `excluded_because` stubs** citing the covering §1.8 instance): entities 12, state_machines 14, calculations 12, validations 8, endpoints 6, errors 30, rbac 4, cross-cutting layers 6, consistency_model 1.

**Verified coverage**: 78/78 endpoints exercised by real call objects; 76/76 error codes referenced; 62/62 validation priorities cited in `grounds`; 111 instance names globally unique across both design files; no YAML anchors/aliases. I also corrected a stale header comment in SCAFFOLD.yaml (it claimed 79 endpoints / 55 errors; now 78 endpoints / 76 errors / 62 validations / 2 OCC rules / 7 roles).

## Step 3: Copy shared files — 2026-09-02T17:36:29.409Z

Copied `./INSTRUCTION.md` → `tasks/task_2423_exchange_replacement_property_sponsorship/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-02T17:55:16.959Z

PRD complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2423_exchange_replacement_property_sponsorship/workspace/PRD.md` — 591 lines, ends at the final row of the §5 error table (no truncation, no audit footer).

**Sections written**
- §1 Introduction (two-clocks framing, crippled-trust powers, silent failure modes)
- §2 Global Specifications, twelve subsections: 2.1 RBAC (7 roles, identity translation), 2.2 response structure (byte-identical to `skills/prd-bench-doc-generator/section-2.2-response-structure.md`, verified), 2.3 Pagination, 2.4 Logical clock and deadline arithmetic, 2.5 Common resource properties (incl. the three journal entities that carry no `updated_at`/`version`), 2.6 Trust posture precedence, 2.7 Money/ratios/rounding (reported-vs-enforced asymmetry), 2.8 OCC (both rules), 2.9 Identifier resolution (all 16 not-found codes), 2.10 the full 62-rung rejection ladder, 2.11 Trust ledger and compensating reversals, 2.12 Trustee power restrictions
- §3 Business Logic, nine subsections: property/trust formation, offering + 5-step grossed-up capital stack, financing + master lease, investor qualification (two independent status dimensions, 3-way min cap), exchange files and the 45/180-day clocks, subscriptions and the 4-hop closing cascade + rescission reversal, operations (rent/debt service/capital needs/reserve), distributions (both variants, round-then-sweep allocation) and tax statements (both conventions), exit/liquidation/successor exchange files
- §4 Endpoint Definitions (4 columns exactly)
- §5 Error Code Catalogue (2 columns exactly)

**Coverage verification (scripted against SCAFFOLD.yaml)**
- Endpoints: 78/78 rows, every row 4 columns
- Errors: 76/76 unique ids, statuses copied from the scaffold
- Entities: all 16 covered; 160/160 scaffold identifiers (entity fields, request bodies, query params, computed-read output fields) appear verbatim in backticks — 0 missing; all path params present; all enum members present
- Validations: 62/62 rungs enumerated in §2.10; calculations: all 21 (including the 3 with variants) expressed in prose with pinned evaluation/rounding order; state machines: all 13, all 46 transitions and all state names covered
- §3 Path Purity: 0 backticked tokens in §3 start with `/`, are a bare HTTP method, or combine method+path
- No pseudocode (only the two §2.2 JSON fences), no operator syntax, no fuzzy-word hits

**Two scaffold gaps resolved in prose** (worth flagging): (1) a consent tally that falls short of `consent_threshold_pct` has **no** error id anywhere in the catalogue, so the PRD specifies it as a successful 200 that stores `consented_units`/`consent_pct` and leaves the event in `PROPOSED`; (2) `rent_kind` has no declared enum in the scaffold, so it is described as a provenance label (base vs supplemental) with no arithmetic effect rather than inventing members. Also, per the hard constraint, neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

**Orchestrator truncation check (per known generator failure mode):** independently verified — 591 lines, tail ends at the last `ERR_` table row (a real section boundary), 76 error rows in §5, 78 endpoint rows in §4, and 0 occurrences of the difficulty instruction string in PRD.md.

## Step 5: Generate unit tests — 2026-09-02T19:34:24.454Z

Generation is complete. All four remaining test modules are written and the full suite verifies clean.

## Files written

**`workspace/test_helpers/`** (9 modules, unchanged this round): `__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py`

**`workspace/test_suite/`** — `conftest.py` + 18 numbered modules, **145 tests**:

| Queue | Files | Tests |
|---|---|---|
| A (Difficulty §1.8) | `test_01`–`test_09` | 63 |
| B (Corner §1.9) | `test_10`–`test_18` | 82 |

New this round: `test_15_rejection_sweeps.py` (23), `test_16_role_and_ownership_authority.py` (4), `test_17_concurrency_and_version_layers.py` (4), `test_18_read_your_writes.py` (1).

## Instance coverage

- **Queue A: 18 / 18** non-stub difficulty instances translated, every one with ≥2 tests.
- **Queue B: 76 / 77** non-stub corner instances translated (entities 12, state_machines 12, calculations 8, validations 7, endpoints 5, errors 23/24, rbac 4, cross_cutting_complexity_layers 4, consistency_model 1). The 16 `excluded_because:` stubs were not translated.

**One instance skipped** — `Corner/errors/capital_need_capital_call_rejected_then_void_after_funding_rejected`. It asserts `ERR_CAPITAL_NEED_INVALID_STATE` for voiding a `FUNDED` capital need, but PRD ladder rung 24 states voiding requires `IDENTIFIED` **or** `FUNDED`, so the PRD does not uniquely derive the asserted refusal. Per the design contract the gap stays a gap: no weakened assertion, no xfail, no placeholder.

## Verification performed

- Every test carries exactly one `Design:` line, it is the last docstring line, and all 145 tags resolve to a real non-stub instance (verbatim name match against both yaml indices). Zero untagged, dual-tagged, dangling or stub-pointing tags.
- **PRD-citation pass:** 187 `PRD:` quotes, all whitespace-normalised-verbatim substrings of `PRD.md`; every test carries at least one ≥8-word quote. Two test_08 docstrings that had only a short ladder-rung quote were upgraded to the full §3.4/§3.8 rule sentences.
- **Scaffold-citation pass:** no occurrence of "scaffold" anywhere in `test_suite/` or `test_helpers/`.
- All 155 error-id/HTTP-status pairs asserted in the new files cross-check against `HTTP_STATUS_CODES`; every `ERR_*` string exists in `ApiErrorId`.
- `pyflakes` clean across all 18 modules (no unused imports, no undefined names); every module imports cleanly and `pytest --collect-only` collects 145 tests.

## Notable PRD-over-design adjudications in the new files

- Instance 428's premature exit close on an `OPERATING` trust is `ERR_TRUST_INVALID_STATE` (rung 12), not the design's `ERR_EXIT_INVALID_STATE` (rung 25); its second-consent payload uses the declared enum member `WITHHOLD` rather than the undeclared `DISSENT`.
- Instances 337/463 claim a `DRAFT` offering has `ppm_version` 0; PRD §3.2 says creation is `ppm_version` 1.
- Instance 414's stale-PPM test asserts `ppm_submitted_by_user_id` rather than `ppm_document_reference`, which the GET representation does not declare.

I did **not** execute the live suite: `workspace/implementation/` is off-limits per the directive, so a run would only measure a concurrently-generated server. The suite is ready for whoever owns the Step 7 sweep.

**Orchestrator note (path relocation):** the test generator wrote its output to `workspace/test_helpers/` and `workspace/test_suite/`, but the entrance skill's output contract places both at the task root. I moved both directories together (`workspace/test_{helpers,suite}` → `{task_dir}/test_{helpers,suite}`) and deleted their stale `__pycache__`. The sibling relationship is preserved, which is what matters functionally: `prd-bench-local-runner`'s `executor.py:134` inserts `Path(test_dir).parent` onto `sys.path` so `from test_helpers import ...` resolves. No absolute paths appear anywhere in `test_suite/` or `test_helpers/`, so no source edits were needed.

## Step 6: Generate implementation — 2026-09-02T19:34:24.454Z

Implementation complete and verified.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2423_exchange_replacement_property_sponsorship/workspace/implementation/`)

**Launcher / infra:** `start.sh` (executable; guarded `pip install` then `exec python3 app.py`, binds `0.0.0.0:$PORT`, default 10000), `requirements.txt` (`flask>=2.0`), `app.py` (registers 15 blueprints, `strict_slashes = False`, ApiError/HTTPException/500 handlers emitting the error envelope).

**Core modules:** `util.py` (exact-rational + rounding + logical-date helpers), `constants.py` (roles, read-role sets, all enums, numeric constants), `errors.py` (79-code catalogue → HTTP status, `ApiError`), `response.py` (success/created/array/error envelopes, pagination meta), `clock.py` (logical clock, startup `2026-08-01T00:00:00Z`), `db.py` (16 in-memory dicts, journal-vs-versioned rows, one `version` bump per row per request), `middleware.py` (rungs 1/2/5, field coercion, pagination/filters).

**Services:** `services/calc.py` (all 21 PRD calculations), `services/domain.py` (lookups, posture gating, ledger + replay balances, the 4-hop subscription close, 3-hop loan reprice, rescission reversal, 6-step exit close).

**Blueprints (15) → 78 endpoints:** `clock_routes` 1, `properties` 5, `trusts` 7, `offerings` 8, `investors` 6, `exchange_files` 4, `identifications` 4, `subscriptions` 6, `loans` 5, `leases` 5, `ledger` 2, `capital_needs` 5, `distributions` 7 (incl. the 2 allocation reads), `tax_statements` 4, `exits` 9 (6 exit-event + 3 exit-consent).

## Verification

- **Route parity:** the implemented method+path set diffs **identical** against the 78 rows of the PRD §4 endpoint table.
- **Boot:** `start.sh` launched twice on free ports (18423, 18424) from a cold process; both served requests immediately. A fresh boot shows every collection at `total_count: 0` and the clock back at `2026-08-01T00:00:00.000Z` — nothing is seeded and nothing is written to disk (in-memory dicts only).
- **End-to-end smoke (all green):** property → acquire → trust → loan commit → offering → capital-stack → submit-PPM → declare-effective → lease execute → open-funding → loan fund → 2 investors (verify + suitability) → 2 exchange files + identifications → 2 subscriptions → closes (trust auto-flipped to `OPERATING`, sponsor load / acquisition / initial-reserve legs booked, `units_issued` 1000) → rent posting + debt service → capital need fund/void with compensating `REVERSAL` → distribution declare/pay with round-then-sweep allocations (`[21299657, 21299658]`, residual `-1`) → tax statements under both conventions + issue → exit propose/consents/short tally (stays `PROPOSED`)/passing tally (trust `WINDING_DOWN` + posture `FROZEN`)/close (net proceeds, property `DISPOSED`, liquidating distribution, successor exchange files).
- **Negative paths spot-checked:** 401 unauthenticated, 403 unauthorized / not-owner / segregation-of-duties, 400 malformed body, 404 unknown route, 405 wrong method, 412 `ERR_STALE_TRUST_VERSION`, 409 overlap/duplicate/frozen, 422 `ERR_CAPITAL_CALL_PROHIBITED`, `ERR_DISTRIBUTION_PERIOD_NOT_ENDED`, `ERR_NO_CONSENTS_RECORDED`, `ERR_OFFERING_CAPACITY_SHORTFALL`.

## Notable interpretation calls

- Rung order follows the PRD §2.10 ladder cross-checked against the scaffold's `applies_to` table for all 62 rungs; the error id for exit-event from-state is `ERR_EXIT_INVALID_STATE` (not `..._EVENT_...`).
- Undeclared from-state checks (investor accreditation/suitability dimensions) return 400 `ERR_INVALID_REQUEST` and are evaluated *after* all declared rungs, so e.g. rung 30 fires before the `UNVERIFIED` check.
- Ownership (rung 3) and SoD (rung 4) use lenient lookups so a missing row still yields its 404.
- Posture is derived, not stored-by-hand: after an exit closes the trust reads `OPEN` again (property is `DISPOSED`, the event is `CLOSED`), which is the literal §2.6 derivation.

The task's `test_helpers/`, `test_suite/`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml` and all sibling `task_*/` directories were never read or listed.

## Step 7: Run tests and iterate — 2026-09-02T20:05:59.226Z

Clean sweep achieved.

## Summary

**Iterations run:** 2 (each an 8-round parallel `per-test-server` sweep, 145 tests/round).

- Round 1: 139/145 in all 8 rounds — 6 deterministic failures, identical in every round (no flakiness, no load-induced failures).
- Round 2: **145/145 passed in all 8 rounds** (265 s/round).

**Tests deleted:** none. Two assertions were removed / two rewritten under STEP 1c partial-coverage handling:

- PRD-SILENCE — *serialization format of a date-valued input field*. Four assertions demanded `term_end_on` / `term_start_on` be echoed as a bare `YYYY-MM-DD` string (`== "2033-08-31"`). PRD §3.3 and §4 name these fields only as "the `term_start_on` and `term_end_on` bounding the term"; §2.5 pins the ISO-8601-with-three-fractional-digits convention only for `created_at`/`updated_at`. Nothing in PRD determines the wire format, so both "store the supplied date string" and "normalise to a UTC instant" are PRD-faithful. The suite contradicts itself on this point too: `assert_exchange_file` in `test_helpers/assertions.py` *requires* `relinquished_closed_on` to be a full ISO-8601 timestamp even though `fixtures.EXCHANGE_FILE_A` supplies the date-only `"2026-08-05"` — the opposite convention. (`relinquished_closed_on` is defensible because PRD calls it an "instant"; the lease term fields have no such word.) `assert_master_lease` itself never checks the term fields.

**Fixes applied to `test_suite/`:**
- `test_08_period_and_lease_interval_overlap.py` — `TestMasterLeaseClosedIntervals`: dropped the bare-date `term_end_on` assertion from `test_a_successor_sharing_the_incumbents_last_day_is_refused` and the `term_start_on` one from `test_a_successor_starting_the_next_day_is_accepted`; in `test_the_rejected_draft_leaves_the_incumbent_and_the_list_intact` the format literal became a self-consistency check (`row["term_end_on"] == incumbent["term_end_on"]`), which preserves the "list intact" intent without asserting an unspecified format. The `ERR_LEASE_TERM_OVERLAP` / closed-interval / `total_count == 2` assertions — the PRD-covered core of all three tests — are untouched.
- `test_14_endpoint_behaviours.py` — `test_termination_preserves_the_history_and_withdraws_the_rent_capability`: same substitution against the lease as created. The `status == "TERMINATED"`, `executed_at` preservation and `ERR_FORBIDDEN_NOT_OWNER` rent-refusal assertions are untouched.

**Fixes applied to `test_helpers/`:** none needed.

**Fixes applied to `implementation/`:**
- `workspace/implementation/services/domain.py` — `bucket_balance()` and `recompute_trust()` were summing `unreversed_entries()` (which drops any entry named by a `REVERSAL`) instead of every entry in the bucket. This double-counted every compensating reversal: a rescission subtracted the equity twice (operating read 420,000,000 instead of 720,000,000) and a capital-need void added the reserve draw back twice (reserve read 55,000,000 instead of 30,000,000). Both now sum `entries_of_trust()`, per PRD §2.11: "A trust's `operating_balance_cents` is the sum of the signed amounts of its `OPERATING` entries and its `reserve_balance_cents` is the sum of the signed amounts of its `RESERVE` entries" — the reversal cancels precisely *because* both legs are counted. The `unreversed_entries()` filter remains correctly in place only where PRD scopes it to `entry_type`-filtered aggregates: `final_cash_gross()` (distribution `FINAL_CASH`) and `routes/tax_statements.py` (rent/interest totals).

This single implementation defect accounted for 2 of the 6 failures; the other 4 were the PRD-silent format assertions. No implementation check was weakened, no endpoint/field/side-effect was added, no data is seeded, and storage remains in-memory dicts only.

**Orchestrator verification of the sweep artifacts (per the known "claimed clean sweep with no artifacts" failure mode):** independently re-read all 8 `workspace/implementation/results.{1..8}.json` — every one parses and reports `passed=145 total=145 failed=0`, all written at the same wall-clock minute (19:54). Claim confirmed.

## Step 8: Finalize PRD — 2026-09-02T20:16:18.372Z

Done. `PRD_FINALIZED.md` written.

## Line counts
- `PRD.md`: 591 lines
- `PRD_FINALIZED.md`: 593 lines
- Delta: **+2 lines (+0.34%)**; 2 edits total (1 insert, 1 revise).

## Changes

- **§2.5 (Common Resource Properties)** — *insert* — new paragraph pinning that the `created_at` timestamp convention is the API-wide convention for time: every moment- or calendar-day-valued field (client-supplied and server-derived alike) is held as a UTC instant and reported as ISO 8601 UTC with three fractional digits and `Z`; unstamped fields are null; a bare `YYYY-MM-DD` on input is read as `00:00:00.000Z` on that date and a non-`Z` offset is normalised to UTC; a bare date is therefore echoed back in full timestamp form, never as the bare string. — `implementation/middleware.py:154` (`req_dt`), `implementation/util.py:84` (`parse_dt`) / `util.py:111` (`fmt_dt`), `implementation/response.py:24` (`jsonable`)
- **§3.3 (master lease drafting)** — *revise* — "The term is a **closed** interval" widened to "a **closed** interval of calendar days", naming that only the date part of the two instants bears on the rung-5 start≤end check, the overlap test and the §3.8 covering-lease search. — `implementation/routes/leases.py:31`, `routes/leases.py:49`, `implementation/services/domain.py:119`

**No edit for the `bucket_balance()` / `recompute_trust()` fix.** PRD §2.11 already uniquely determines it ("a trust's `operating_balance_cents` is the sum of the signed amounts of its `OPERATING` entries…"), and §2.11's final paragraph already scopes the reversed-entry skip to `entry_type`-filtered aggregates, which is exactly where `unreversed_entries()` survives (`services/domain.py:422` `final_cash_gross`, `routes/tax_statements.py`). This was a pure impl-vs-PRD mismatch that the fix resolved in the PRD's favour — nothing to pin.

## Pre-edit search log

**Edit 1 — §2.5 time-serialisation convention**
- (a) Subject: how every date/instant-valued field is parsed, stored and rendered — not just the lease term fields at the Step 7 site.
- (b) Paths enumerated: `grep -rn "req_dt\|opt_dt" routes/ services/` → all ten parse sites (`clock_routes.py:17` `to_iso8601`, `properties.py:33` `contract_close_deadline`, `distributions.py:26-27` `period_start`/`period_end`, `leases.py:26-27` `term_start_on`/`term_end_on`, `loans.py:39` `maturity_on`, `capital_needs.py:23` `needed_by`, `exchange_files.py:22` `relinquished_closed_on`, `exits.py:31` `expected_close_on`); grep of every storage site to confirm the parsed `datetime` (not the raw string) is what lands in the row; `middleware.py:154` `req_dt` → `util.py:84` `parse_dt` (accepts date-only, `T`/space separator, 1–9 fractional digits, `Z` or `±HH:MM`, normalising offsets to UTC); `db.py:98` `serialize` (passes values through untouched, so the row holds real `datetime`s); `response.py:24` `jsonable` → `util.py:111` `fmt_dt` (the single rendering funnel for *every* datetime in every envelope, including list rows and `meta`); server-derived instants `calc.py:70` `exchange_deadlines` / `util.py:126` `end_of_day` / `domain.py:323` `rescission_deadline` / `domain.py:468-469`, `domain.py:486` (successor-file and liquidating-distribution instants); `clock_routes.py:19` (`current_utc` also via `fmt_dt`); and a negative check — `grep "req_str(payload"` over all routes returned 17 fields, none of them date-like, confirming no date field bypasses `req_dt` and survives as a raw string.
- (c) Adjustments made: three. (1) Dropped an initial "any ISO 8601 instant" phrasing to "either a full ISO 8601 timestamp or a bare `YYYY-MM-DD` calendar date", because `parse_dt`'s regex accepts only extended calendar form, not week dates or basic format — the looser claim would have over-promised. (2) Added "A field the server has not yet stamped is reported as null", because `funded_at`, `executed_at`, `paid_at`, `issued_at`, `closed_at`, `effective_at`, `acquired_at` and `property_acquired_at` are all initialised to `None` and `jsonable` emits them as JSON null; without the clause the sentence read as a universal non-null claim. (3) Wrote the field list as illustrative-with-"and the rest" rather than exhaustive, so paths Step 7 never exercised (e.g. `identified_at`, `recorded_at`, `occurred_at`) are covered without the list becoming a closed set that a later reader could treat as excluding others.

**Edit 2 — §3.3 lease-term day granularity**
- (a) Subject: the granularity at which `term_start_on`/`term_end_on` are compared — triggered by edit 1 having just declared these fields to be instants, which risked implying instant-granularity comparisons.
- (b) Paths enumerated: `routes/leases.py:31` (rung-5 start≤end check, `as_date(term_start_on) > as_date(term_end_on)`); `routes/leases.py:42-49` (the `ERR_LEASE_TERM_OVERLAP` closed-interval test, both endpoints through `as_date`, walking sibling trusts by shared `property_id`); `services/domain.py:111-124` `lease_for_period` (the §3.8 covering-lease search, `as_date(period_start)` against `as_date` of both term bounds); `util.py:122` `as_date`. All three comparison sites are uniformly day-granular; no callsite compares the raw instants.
- (c) Adjustment made: scoped the clause to "any term comparison" and enumerated the three actual comparison sites rather than writing a blanket "the time part is discarded" — the time part is *not* discarded from storage or output (edit 1 requires it to be echoed), only from comparison, so the narrower wording keeps both edits mutually consistent. Deliberately left `lease_for_period`'s no-match fallback (first `EXECUTED` lease, else first candidate) undescribed: it is off the Step 7 site and outside the hard scope, and PRD's existing "the single lease … whose term covers the `period_start`" remains under-determined rather than contradicted.

**Orchestrator check:** `PRD_FINALIZED.md` is 593 lines and still ends at the last row of the §5 error table — no truncation introduced.

## Step 9: Complete PRD — 2026-09-02T20:36:50.877Z

`PRD_COMPLETED.md` is written and verified.

## Verification
- Source `PRD_FINALIZED.md`: 593 lines, 116,583 chars. Completed `PRD_COMPLETED.md`: 593 lines, 127,814 chars — **char delta +11,231**, line count unchanged (every change is an in-paragraph insert or revision; no new paragraphs, no new sections).
- All 29 headings identical (`diff` of heading lines is empty). §4 retains all **78** endpoint rows; §5 retains all **76** error rows; file ends at the last §5 row (`ERR_NO_CONSENTS_RECORDED | 422`). 37 lines differ, one per change.

## Counts
- **29 ambiguity pins**, **8 mismatch revisions** (37 changes total; 28 pure inserts, 9 in-place revisions).

## Changes
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; `created_at` ties broken by server insertion order; out-of-enum filter values match no rows rather than being rejected — `middleware.py:150-176`
- §2.4 — insert — ambiguity — clock 200 carries `current_utc` alone; the clock is *set* (may move backwards), and accepts bare-date and offset-bearing inputs — `routes/clock_routes.py:14-27`
- §2.5 — insert — ambiguity — a row's `version` advances at most once per request however many of its fields that request rewrites; a no-op recomputation leaves it alone — `db.py:touch`
- §2.6 — revise — mismatch — `LIQUIDATING` posture exemption narrowed to declaration and payment; voiding is frozen-gated whatever the `kind` — `routes/distributions.py:149`
- §2.7 — revise — mismatch — only `ltv_pct`, `dscr`, `consent_pct`, `raw_share_cents` are rounded to 4dp; `occupancy_rate`, `reserve_target_pct`, `load_pct`, `reserve_funding_pct`, `consent_threshold_pct` are echoed as the exact rational supplied — `middleware.py:req_ratio`
- §3.1 — insert — ambiguity — expiring a contract before its deadline → `ERR_PROPERTY_INVALID_STATE` — `routes/properties.py`
- §3.1 — revise — mismatch — open-funding requires posture *not* `FROZEN` (not `OPEN`); offering/facility are existence not uniqueness tests, decided after the property test, `ERR_OFFERING_NOT_EFFECTIVE` then `ERR_LOAN_INVALID_STATE` — `routes/trusts.py`
- §3.2 — insert — ambiguity — `ppm_document_reference` is validated then discarded — `routes/offerings.py`
- §3.2 — insert — ambiguity — an absent facility contributes zero principal to the stack — `services/domain.py:82-84`
- §3.2 — insert — ambiguity — `load_pct_bps` is capped at 9999 when it would round to 10000 — `services/calc.py:capital_stack`
- §3.2 — insert — ambiguity — the capital-stack read is computed live in every status including `DRAFT`, and `equity_remaining_cents` may be negative — `routes/offerings.py`
- §3.3 — insert — ambiguity — zero annual debt service yields `dscr` `0.0000` and the coverage test *passes*; LTV takes precedence when both fail — `services/calc.py:loan_dscr`
- §3.3 — revise — mismatch — lease termination stamps no instant and rewrites no figure; its whole effect is the loss of an `EXECUTED` lease, and a terminated lease still supplies terms for periods its term covers — `routes/leases.py`
- §3.4 — insert — ambiguity — `evidence_reference` is validated then discarded — `routes/investors.py`
- §3.4 — insert — ambiguity — every wrong-state investor-dimension transition is `ERR_INVALID_REQUEST` (400), not a dedicated 409 — `routes/investors.py`
- §3.4 — insert — ambiguity — the verification-method test precedes the `UNVERIFIED` from-state test and is skipped absent `suitability_offering_id`; suitability review is not posture-gated — `routes/investors.py`
- §3.5 — revise — mismatch — `sequence_no` is a monotone filing counter over all rows ever filed on the file, revoked included, never reassigned — `routes/identifications.py`
- §3.5 — revise — mismatch — the "first `ACTIVE` identification takes `sequence_no` 1" sentence reworded to match that counter — `routes/identifications.py`
- §3.5 — insert — ambiguity — marking a file expired before its deadline → `ERR_EXCHANGE_FILE_INVALID_STATE` — `routes/exchange_files.py`
- §3.6 — insert — ambiguity — hop two's `FUNDED` facility and `EXECUTED` lease are cascade *conditions*, not request gates: the close succeeds, the trust stays `FUNDING`, hops 2–4 are silently skipped — `services/domain.py:340`
- §3.6 — insert — ambiguity — rejecting a `REVISION_REQUIRED` row still advances the offering's `version` (forced recomputation) — `routes/subscriptions.py`
- §3.7 — insert — ambiguity — `rent_kind` is a free-form non-blank string, not a closed enum; `amount_cents` ≥ 1 — `routes/trusts.py:113-135`
- §3.7 — insert — ambiguity — rent posting returns **201 with the created `TrustLedgerEntry`**, not the trust — `routes/trusts.py:113-135`
- §3.7 — insert — ambiguity — debt service: `amount_cents` ≥ 1, no `FUNDED` facility → `ERR_LOAN_INVALID_STATE`, returns 201 with the created entry — `routes/trusts.py:138-152`
- §3.7 — insert — ambiguity — a `funding_source`/role mismatch → `ERR_UNAUTHORIZED` (403), decided after resolution and body but before posture, lifecycle and from-state — `routes/capital_needs.py:68-71`
- §3.7 — revise — mismatch — a `RESTRICTED` posture blocks `MASTER_TENANT` funding as well as `RESERVE` draws (the gate guards the endpoint, not the draw) — `routes/capital_needs.py:74`
- §3.7 — insert — ambiguity — voiding a `FUNDED` need off `OPERATING` → `ERR_TRUST_INVALID_STATE`, tested *after* the need's own from-state — `routes/capital_needs.py:111-114`
- §3.8 — insert — ambiguity — lease selection falls back to the earliest `EXECUTED`, then the earliest candidate; no lease at all gives zero accruals and zero replenishment — `services/domain.py:111-124`
- §3.8 — insert — ambiguity — accrual facility is `FUNDED`, else `COMMITTED`/live, else any facility on the trust — `routes/distributions.py:16-17`
- §3.8 — insert — ambiguity — the two replenishment legs carry `entry_type` `RESERVE_FUNDING` and `source_kind` `DISTRIBUTION` at the payment's `occurred_at` — `routes/distributions.py:133-136`
- §3.8 — insert — ambiguity — the tax statement's `trust_id` and `subscription_id` are not cross-checked — `routes/tax_statements.py:72-76`
- §3.8 — insert — ambiguity — held days are floored at zero as well as capped at 365, and are keyed on the *trust's* `property_acquired_at`, so depreciation is zero while that is unset — `services/calc.py:192-208`
- §3.8 — insert — ambiguity — a zero `units_issued` or zero unit-day total yields a share of zero; unit-days are *not* floored, so a subscription closing after year end carries a negative weight — `services/calc.py:211-218`, `routes/tax_statements.py:47-59`
- §3.8 — revise — ambiguity — issuance tests the subscription's `CLOSED` status *before* the statement's `DRAFT` from-state — `routes/tax_statements.py:123-126`
- §3.9 — revise — mismatch — exit close performs no `springing_llc_armed` test; the terminal state is read off `exit_mode` alone and the flag is necessarily already true — `services/domain.py:508`
- §3.9 — insert — ambiguity — consent checks owner, then subscription status, then event status; the subscription need not belong to the event's trust — `routes/exits.py:134-153`
- §4 preamble — insert — ambiguity — the optional `reason`/`review_note` fields are string-validated (empty accepted, non-string → `ERR_INVALID_REQUEST`) but never persisted or echoed — `middleware.py:82-90`

**Orchestrator verification:** independently confirmed `PRD_COMPLETED.md` — 593 lines, 76 error rows, 78 endpoint rows, 29 headings (identical count to `PRD_FINALIZED.md`), ends at the last §5 error-table row. No truncation, no section loss.

---

# Pipeline complete

All nine steps finished. `workspace/PRD_COMPLETED.md` exists; the final 8-round `per-test-server` stability sweep is green at 145/145 in every round (`workspace/implementation/results.{1..8}.json`).
