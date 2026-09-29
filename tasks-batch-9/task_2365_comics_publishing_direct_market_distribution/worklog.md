# Worklog — task_2365_comics_publishing_direct_market_distribution

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2365_comics_publishing_direct_market_distribution/` and `workspace/` subdirectory (name pre-allocated by caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T06:24:23.000Z

All three artifacts are written and the linter is clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2365_comics_publishing_direct_market_distribution/`)
- `SCAFFOLD.yaml` (§1.0–§1.7, 144 KB) — keys: scenario, domain_name, api_prefix, complexity_profile, response_envelope, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles. Neither design key present.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`.
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`.

**Verdict block (verbatim)**

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2365_comics_publishing_direct_market_distribution/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2365_comics_publishing_direct_market_distribution/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2365_comics_publishing_direct_market_distribution/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    72
  §1.1 entities declared:     14
  §1.8 instances scanned:     26
  §1.9 instances scanned:     73
  Calls scanned (§1.8+§1.9):  2039

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Counts**
- §1.1–§1.7: 14 entities, 11 state-machine blocks (Issue carries two independent dimensions: production_status and commercial_status), 2 optimistic-concurrency rules (stale Title version on assignment create, stale Issue version on print-run create), 12 calculations, 28 validation priorities, 72 endpoints, 59 error codes, 6 roles (EditorInChief, ManagingEditor, SalesDirector, RoyaltyAccountant, Creator, Retailer).
- §1.8 difficulty design: 9 rules / 26 instances — dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 3, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 4, cross_entity_state_dependency 3, resource_temporal_overlap 3, compensating_invariant 3.
- §1.9 corner design: 9 sections / 97 instances = 73 full recipes + 24 `excluded_because` stubs — entities 12, state_machines 17, calculations 9, validations 9, endpoints 6, errors 32, rbac 6, cross_cutting_complexity_layers 5, consistency_model 1.

**Verification beyond the linter**
- All 59 error codes are referenced by a §1.8 or §1.9 instance (0 uncovered); the 24 stub citations all resolve to real §1.8 instance names, and no name collides across the two design files.
- Section/claim_type vocabulary taken only from `references/claim-extraction-guide.md`; no sibling task directory was read.
- Three SCAFFOLD.yaml reachability repairs were made while building §1.9: validation priority 10 now applies to `POST /comics/titles/{id}/issues` (makes ERR_TITLE_NOT_GREENLIT coherent on issue creation); priority 8 carves out cancel-on-SHIPPED and reverse-on-PAID so priority 9's ERR_RETURNS_NOT_PERMITTED / ERR_STATEMENT_ALREADY_PAID are reachable; RetailerOrder gained INVOICED/DRAFT/SUBMITTED → CANCELLED transitions (INVOICED → CANCELLED carries the ledger-restoring side effects).

## Step 3: Copy shared files — 2026-09-02T06:24:23.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2365_comics_publishing_direct_market_distribution/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T07:25:12.000Z

PRD generated and audited.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2365_comics_publishing_direct_market_distribution/workspace/PRD.md` — **459 lines**, ~12,360 words. Ends at §5 as required; no audit/contract text written into the file.

**Sections**
- §1 Introduction (3 paragraphs from `scenario`, mounts under `/comics`)
- §2 Global Specifications, 11 subsections: 2.1 Roles & Identity Headers · 2.2 API Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 The Logical Publishing Clock · 2.5 Record Identity, Timestamps & Row Versioning · 2.6 Derived Status, Roll-Ups & Cascades · 2.7 Ledger Discipline & Exact Compensation · 2.8 Money, Units, Basis Points & Rounding · 2.9 Stale-Parent Protection (both OCC rules) · 2.10 Path Resolution & the 28-step ordered check ladder · 2.11 Segregation of Duties & Non-Returnable Terms
- §3 Business Logic, 9 workflow subsections: greenlight/royalty-pool commitment · issue slate & production board (dual status dimensions) · delivery, slip measurement & 4-hop slip cascade · catalogs & solicitation · variant covers, order book & FOC lock (allocation walk) · invoicing, shipping & order compensation · printings, reprints, release & downstream editions · revenue events & royalty accounting (channel pools, cover strike, pro-rata remainder, recoupment) · title cancellation cascade
- §4 Endpoint Definitions (72-row, exactly-4-column table + a filter paragraph)
- §5 Error Code Catalogue (59-row, exactly-2-column table)

**Coverage audit (all three Hard Contracts PASS)**
1. **Field-Name Coverage — PASS.** All 106 entity field names and all 66 endpoint input identifiers appear verbatim in backticks (script-verified against `SCAFFOLD.yaml`); nested keys `variant_cover_id`, `qty`, `included_net_cents`, `channel_pool_cents`, `creator_share_cents` also present. One gap found and fixed during the audit: `catalog_id` was missing (added in §3.4).
2. **Rule Coverage — PASS.** All 28 validation priorities emitted as an explicit ordered ladder with every scaffold `error_id` landing on its own priority and every `applies_to` scope enumerated; all 59 error codes present with HTTP statuses matching the scaffold exactly (0 mismatches); all 52 transitions across the 11 state-machine blocks described, including the 3 parallel-dimension pairs and every system/cascade edge; all 11 calculations rendered in prose with every constant value embedded (verified numerically: 250-carton, 500/250 minimums, 150 reserve, 8%/35%/20%, 40/45/50/55% tiers, 2,500/10,000/25,000 unit thresholds, 995 cents = $9.95, 50,000 cents = $500.00, channel multipliers 10000/20000/12500/40000 over 100,000,000, 7/21-day slip bands, 21/30/60/90-day windows, 3 negotiation rounds); both OCC rules with their 412 codes; all 72 endpoints matched with byte-identical role sets.
3. **§3 Path Purity — PASS.** Zero backtick tokens in §3 begin with `/`, name a bare HTTP method, or combine method + path (script-verified over the §3 span).

Also verified: no pseudocode operators (`==`, `>=`, `+=`, `min()`, `floor()`, `IN`) anywhere outside code fences, and no fuzzy qualifiers ("approximately", "roughly", "conservatively") — one borderline "about to be computed" was reworded.

**Scaffold discrepancies handled** (trusting the tables over the header comment, which understates counts): actual content is 14 entities, 72 endpoints, 59 errors, 11 calculations, 11 state machines. Two internal conflicts reconciled in prose rather than picked arbitrarily: `printing_number` (entity says max+1 over `PLANNED`/`PRINTED`, endpoint side-effect says non-cancelled count+1 → phrased to satisfy both) and print-run cancel's `printed_units` recompute (noted as a no-op since a planned run never contributed). The `production_status` derivation was phrased as exact negations to avoid the vacuous-truth trap, with an explicit "otherwise the value does not move" fallback covering kick-backs and the reachable `ERR_REQUIRED_CRAFT_STAGES_MISSING` state.

The two withheld design files were never opened, grepped, or referenced.

## Step 5: Generate unit tests — 2026-09-02T07:25:12.000Z

Test infrastructure and test suite are complete for `task_2365_comics_publishing_direct_market_distribution`.

## Files created

**Stage 1 — `test_helpers/` (9 files)**
`types.py` (UserRole + 21 status/vocabulary enums, 14 record TypedDicts), `api_errors.py` (all 59 error IDs + the PRD §5 status map registered at import), `api_client.py` (`ApiClient` over `/comics`, one method per §4 endpoint row), `constants.py` (every PRD magic number/vocabulary), `test_users.py` (per-role headers plus `make_creator_headers` / `make_retailer_headers` for the two entity-backed roles), `factories.py` (payload builders with unique-value generation), `assertions.py` (domain assertions for issue dimensions, retailer ledgers, allocations, invoices, print runs, statement lines/money, listings), `fixtures.py` (granular steps + 12 composite state builders), `__init__.py` (barrel, 109 names).

**Stage 2 — `test_suite/`**: `conftest.py` + 18 test files, **223 tests**.

## Coverage

| Queue | Instances | Tests |
|---|---|---|
| A — Difficulty (§1.8) | **26 / 26** covered, all with >=2 tests | 85 |
| B — Corner (§1.9) | **73 / 73** non-stub covered, all with >=1 test | 138 |

**Zero instances skipped.** The 24 `excluded_because` corner stubs were not translated (audit rejects any test tagged to one).

## Verification run

An AST-based audit over the whole suite confirms: every test has exactly one `Design:` line as the final docstring line; every tag resolves to a real, non-stub instance in the source yaml; every `PRD: "..."` quote is a whitespace-normalized verbatim substring of `PRD.md`; no `skip`/`skipif`/`xfail`; no mention of the design documents. `pytest --collect-only` collects 223/223, `test_helpers` imports clean, no cross-imports between test files.

## Key findings

- **Fixed a Stage 1 defect found by two subagents.** `fixtures.setup_camera_ready_issue` accepted five non-`COVER` assignments at the factory default 5000 bps against a non-cover ceiling of 8500 bps (10000 - 1500 cover participation), so the second acceptance would have hit `ERR_ROYALTY_SHARE_POOL_EXCEEDED`; and it left the clock at `2026-08-21`, past the default catalog `submission_deadline` of `2026-08-20`, so every camera-ready composite would have hit `ERR_SOLICITATION_WINDOW_CLOSED`. Added `CAMERA_READY_SHARES` (5000/1500/800/700/500 = 8500), an `assignment_overrides`/`royalty_shares` pass-through threaded down through `setup_solicited_camera_ready_issue` and `setup_locked_order_book`, and moved the default delivery clock to `2026-08-19`.
- **Several design recipes assert outcomes the PRD contradicts**; in each case the test asserts the PRD's value and the deviation was reported rather than the assertion weakened. The recurring ones: `total_units`/`total_ordered_units` being non-zero before the FOC lock (PRD §2.7/§3.5 make both 0 until the lock freezes them), `page_fee_cents`/`delivered_pages` expected `null` where the PRD declares `0`, `production_status` staying `PLANNED` after a stage booking (PRD §3.2 flips it to `SCRIPTING` at booking, corroborated independently by two files), and a title-issue listing expected in `target_on_sale_date` order where PRD §2.3 mandates `created_at` ascending.
- Two recipe assertions were dropped as not uniquely derivable and reported as gaps: an exact `version + 1` delta on the title/issue across an offer-plus-acceptance, and the stored instant of `submission_deadline` (not among PRD §2.4's midnight-UTC date fields).

## Step 6: Generate implementation — 2026-09-02T07:25:12.000Z

The implementation is complete and verified.

## Files created
All under `/home/ubuntu/github/CodingPRD/tasks/task_2365_comics_publishing_direct_market_distribution/workspace/implementation/` (12 files, ~3,800 lines):

- `start.sh` (executable) — `cd`s to its own dir, installs Flask only if the import fails, then `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000), no reloader, no debug
- `requirements.txt` — `Flask>=2.2`
- `app.py` — app factory, blueprint registration, envelope-shaped error handlers for `ApiError` / `HTTPException` (404 -> `ERR_NOT_FOUND`, 405 -> `ERR_METHOD_NOT_ALLOWED`) / unhandled
- `core.py` — 14-dict in-memory `Store`, logical clock, envelope + `meta` builders, `X-User-ID`/`X-User-Role` RBAC, validators, pagination, request-scoped change tracking, the 60-entry error-code -> HTTP-status table
- `calc.py` — the named calculations (cover walk order, ratio/exclusive allocation, invoice totals, both print-run bases, royalty pool split and accrual), with the rounding vocabularies kept strictly apart
- `services.py` — entity getters, all ten ledger recomputes (always full recomputes, never deltas), production-status derivation, slip / FOC-lock / title-cancel cascades, 14 serializers
- `routes/` — `roster.py`, `production.py`, `catalogs.py`, `retail.py`, `finance.py`, `__init__.py`

## Endpoint count
**72 endpoints — an exact match with `SCAFFOLD.yaml`.** I diffed Flask's `url_map` against the scaffold's method+path pairs programmatically: zero missing, zero extra. (My earlier working count of 66 was wrong; `POST /comics/print-runs/{id}/cancel` and five others were implemented but uncounted.)

## Notable design decisions
- **Storage**: plain dicts keyed by UUID, an insertion sequence for stable `created_at` ASC ordering, and nothing seeded — a fresh boot returns `total_count: 0` for every collection (verified via `start.sh`).
- **Two clocks**: the logical clock (default `2026-08-01T00:00:00.000Z`) drives every temporal rule and the stamps PRD §2.4 enumerates; `created_at`/`updated_at` use wall-clock UTC. All datetimes render with exactly 3 fractional digits.
- **Versioning**: a row's `version` bumps at most once per request and only on real content change, plus the two forced OCC parent bumps (`touch(title)` on assignment create, `touch(issue)` on print-run create).
- **Validation order** follows PRD §2.10 literally, including the counter-intuitive pairs: shape before ownership, cadence before duplicate `issue_number`, double-booked before craft-not-supported, `NO_QUALIFYING_ORDERS` before `REQUIRED_CRAFT_STAGES_MISSING`, `ISSUE_NOT_SOLICITED` before `RETAILER_NOT_ACTIVE`.
- **Ambiguities resolved toward the PRD over the scaffold's shorter prose** where they disagreed: `printing_number` is max+1 over `PLANNED|PRINTED` (not a count of non-cancelled runs); the royalty-pool ceiling is enforced at *acceptance*, not at offer time; termination is legal from `PROPOSED`/`COUNTERED`/`ACCEPTED`/`ACTIVE` unless a stage of that assignment is in flight.
- **Cascades** fire on transition edges only (e.g. the slip cascade runs on entry into `SLIPPED`, not on every recompute), and FOC-lock snapshots every retailer's `cumulative_units_ytd` before walking the order book so exclusive eligibility is not affected by same-request updates.

## Verification
Three throwaway smoke scripts in `/tmp` (outside the task tree; `test_suite/` and `test_helpers/` were never read or touched) all report `FAILURES: 0`:
1. Roster -> production -> catalog -> order -> FOC-lock -> printing -> approval, ending in the 4-hop slip cascade (275 slip days -> `SLIPPED` -> issue back to `UNSOLICITED`).
2. The clean commercial path: FOC-lock allocation, `ENTRY`-tier invoice (23940 + 6000 + 995 handling = 30935), ship with its immutable revenue event, on-sale release with title bubble-up, digital embargo + collected blackout boundaries, reprint sizing, print-run cancel, and statement create/issue/pay/reverse with hand-computed royalty splits (pool 2395 -> cover 239, remainder 2156 -> 431 each with the one-cent top-up to 432) plus advance recoupment and its exact reversal.
3. Negative and edge coverage: missing/unknown headers, pagination bounds, 404/405 envelopes, the bounded 3-round negotiation, pool ceiling at accept, stage guards, solicitation withdrawal, retailer suspend/reinstate.

Two implementation behaviours my first-draft assertions got wrong turned out to be spec-correct, so no code changed: a fresh issue is `PLANNED` (not `SCRIPTING`) until a script stage is booked, and an out-of-range `delivered_pages` is `ERR_INVALID_REQUEST` (400) per PRD line 212 rather than a 422.

## Step 7: Run tests and iterate — 2026-09-02T10:05:00.000Z

All three matches are comments asserting the absence of seeding — no actual persistence, no SQLite, no `/tmp`, no `json.dump`. The loop is complete.

## Summary

**Iterations run:** 3 sweeps (8 rounds each), with one fix batch applied after sweep #1.

**Final sweep result — clean.** Across all 8 rounds of 222 tests: **zero assertion failures**, and **all 222 tests passed in at least one round** (0 tests never passed). The 628 non-passes were 100% harness artifacts, not artifact defects:
- 626 × `subprocess.TimeoutExpired: 'pids=$(lsof -ti:PORT -sTCP:LISTEN ...)' timed out after 5 seconds` at *setup*
- 2 × transport-layer `ConnectionResetError(104)` / `RemoteDisconnected` (the only 2 entries in the `failed` bucket; both tests passed in the other 7 rounds)

Root cause of the noise: the host was running 180+ concurrent sibling `prd-bench` pipelines with **99 holders** in the shared `~/.cache/prd-bench-local-runner/ports.tsv` registry (load average 130-230 on 32 cores). Under that load `lsof` exceeds the runner's own 5s port-probe budget. This matches the prompt's NOTE and the recorded memory.

**Infrastructure obstacle worth flagging for future runs:** two earlier waves had all their rounds SIGTERMed mid-run. The cause was *my own polling harness*, not a foreign process — the Bash tool sends **SIGTERM to the whole process group** when a command hits its timeout, which reaped the rounds launched from that group. Wrapping each round in `setsid nohup ... & disown` (see `/tmp/t2365_sweep3c.sh`) made them survive; rounds only completed once detached. Any long-running sweep polled across multiple Bash calls needs this.

### Tests deleted (1)
- **`test_suite/test_11_state_machine_transitions.py::test_releasing_the_only_planned_issue_completes_the_title`** — STEP 1b **unique-derivability collapse (chained-cascade silence)**. PRD line 284 reads "a title **already** `PUBLISHING` moves to `COMPLETED` …"; with `planned_issue_count == 1` the title is `IN_PRODUCTION` when the request starts, so two PRD-faithful readings exist — one transition per event (→ `PUBLISHING`) vs. iterate to a fixed point (→ `COMPLETED`). PRD §2.6 line 101 names only three operations as multi-hop cascades and release is not among them, reinforcing the single-pass reading. Scaffold rule that drove generation: `Corner/state_machines/bubble_up_release_of_the_last_planned_issue_completes_the_title`. The `IN_PRODUCTION → PUBLISHING` edge remains covered by `test_15`'s `test_releasing_the_issue_on_its_target_date_moves_the_title_to_publishing`.

### Fixes applied to `test_suite/` (2 assertion removals, STEP 1c partial coverage)
Both removed a `submitted_at` assertion on a **RetailerOrder** — a field PRD never declares on that entity (§3.5 line 244 enumerates the drafted order's fields and omits it; line 246 mentions no stamp; `submitted_at` belongs to **Solicitation** per §3.4 lines 226/228). Triple-corroborated: absent from `SCAFFOLD.yaml`'s RetailerOrder field list *and* from the suite's own `RetailerOrder` TypedDict in `test_helpers/types.py`.
- `test_13_validation_rules.py::test_submitting_a_draft_order_against_a_solicited_issue_stamps_the_clock` — dropped `assert_instant_equals(submitted["submitted_at"], ...)`; kept the PRD-covered status and version assertions.
- `test_13_validation_rules.py::test_the_non_returnable_gate_stops_only_the_unacknowledged_account` — dropped `assert still_draft["submitted_at"] is None`; kept the exact `ERR_NON_RETURNABLE_ACK_REQUIRED` assertion, the `DRAFT` status, version-unchanged, and both ack-flag assertions.

No assertion was weakened: no `error_id` → HTTP-status downgrade, no boundary relaxation, and `grep` confirms **zero** `skip`/`xfail` markers in the suite. The 6 remaining `submitted_at` assertions (in `test_07`, `test_14`, `test_16`) are all on Solicitation and are PRD-covered.

### Fixes applied to `test_helpers/` — **none**
No fixture, factory, role-header builder, or assertion violated a PRD precondition.

### Fixes applied to `implementation/` — **none**
`services.py::title_issue_went_on_sale` implements the PRD-literal single-pass bubble-up ("a title *already* `PUBLISHING`") and was judged faithful, so the divergence was resolved on the test side per STEP 1b. Storage remains in-memory dicts only, nothing seeded (verified: no SQLite, no `/tmp`, no `json.dump`).

Final state: **222 tests collected**, down from 223.

### Orchestrator verification of the Step 7 exit (added by orchestrator)

The subagent exited without a literal 8/8 `passed == total` sweep, so the orchestrator re-classified all 1776 test executions in `results.{1..8}.json` independently:
- `failed` buckets: 0, 0, 0, 0, 1, 0, 1, 0 — the two entries are transport resets, not assertion failures.
- 628 non-passes total: **626 `lsof_timeout`** (runner's own 5s port probe) + **2 `conn_reset`**. Zero non-passes carry an assertion traceback.
- All 222 tests passed in at least one round; the never-passed set is empty.
- Host state at classification time: load average 250.84 on 32 cores, 183 holders in `~/.cache/prd-bench-local-runner/ports.tsv`.

A reduced-concurrency (2-round) confirmation sweep was launched detached, writing `results.9.json` / `results.10.json`; its outcome is recorded in the Step 9 entry.

## Step 8: Finalize PRD — 2026-09-02T10:12:00.000Z

`PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_2365_comics_publishing_direct_market_distribution/workspace/PRD_FINALIZED.md`.

## Line counts
- PRD.md: 459 lines; PRD_FINALIZED.md: 459 lines — **0.0% line delta** (one existing paragraph extended in place; no lines added or removed).

## Changes (1)
- **§3.7 (line 284) — insert — pins the release bubble-up as single-hop: only one of the two title edges is taken per release, so `IN_PRODUCTION → PUBLISHING` ends the bubble-up without also testing the `COMPLETED` condition, and a title with `planned_issue_count == 1` is left `PUBLISHING` after its only issue goes on sale — `implementation/services.py:409-420` (the `return` after `apply_fields(title, status="PUBLISHING")`), called from `implementation/routes/production.py:482`.**

## Per-edit pre-edit search log

**Edit 1 — §3.7 release bubble-up**
- (a) Subject: server-initiated `Title.status` transitions triggered by an issue going on sale, and every other writer of `Title.status`.
- (b) Impl paths enumerated (grepped `apply_fields(title`, `title_issue_went_on_sale`, `title_first_issue_created`, `PUBLISHING|COMPLETED`, plus read of the release route):
  - `services.py:409-420` `title_issue_went_on_sale` — the Step 7 site: `IN_PRODUCTION → PUBLISHING` then `return`; `PUBLISHING → COMPLETED` guarded by `on_sale >= planned_issue_count` counted over `title_issues`.
  - `routes/production.py:464-483` `release_issue` — the only caller; sets `commercial_status="ON_SALE"` and `on_sale_date` before calling the bubble-up.
  - `services.py:404-406` `title_first_issue_created`, called from `routes/production.py:117` — the other bubble-up edge (`GREENLIT → IN_PRODUCTION`), also single-hop.
  - `routes/roster.py:161` (greenlight) and `roster.py:176` (cancel) — the only client-driven `Title.status` writes; unaffected by the new wording.
  - `services.py:196/205/214` — title ledger recomputes; touch `Title` but not `status`.
  - Checked that `commercial_status == "ON_SALE"` never regresses (slip cascade `services.py:380-396` only unwinds `SOLICITED`/`FOC_LOCKED`; title cancel sets the title `CANCELLED`), so the on-sale count is monotone and the `COMPLETED` edge can still fire on a *later* release even for `planned_issue_count == 1`.
- (c) Wording adjustments made to stay consistent with all of the above: (i) scoped the new sentence to "per release" rather than to bubble-ups in general, so the `GREENLIT → IN_PRODUCTION` edge at `production.py:117` is not re-described; (ii) said the title "is left in `PUBLISHING`" rather than "can never complete", because a later release of a further issue does reach `COMPLETED` under the impl's `>=` comparison; (iii) left the `reaches its planned_issue_count` clause and the trailing "Both the issue's and the title's `version` increment" sentence verbatim, to avoid narrowing the impl's `>=` test or its conditional `apply_fields` version bump.

## Step 7 items that needed **no** PRD edit
- Both `test_13` `submitted_at` assertion removals: `grep -rn submitted_at implementation/` returns hits only in the **Solicitation** paths (`routes/catalogs.py:180` draft → `None`, `catalogs.py:239` submit → `db.now()`, `services.py:608` serializer). The implementation has no `submitted_at` on `RetailerOrder` at all, and PRD §3.5 lines 244/246 already describe order drafting/submission without such a stamp — so PRD and impl already agree; the assertions were test-side bugs (they would have raised `KeyError`). No silence to pin.

## Step 9: Complete PRD — 2026-09-02T10:14:07.000Z

Structure intact; no sections added or removed.

## Summary

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_2365_comics_publishing_direct_market_distribution/workspace/PRD_COMPLETED.md`

- `PRD_FINALIZED.md`: 459 lines / 88,057 chars → `PRD_COMPLETED.md`: 461 lines / 93,894 chars (**+5,837 chars**, +2 lines)
- 33 lines revised in place + 1 new paragraph (the only structural addition, inside §2.5); no new sections
- **37 pins total: 28 ambiguity-pins, 9 mismatch-revisions**

### Changes

- §2.3 Pagination — insert — ambiguity — list ties broken by write sequence, not undefined (`core.py:302`)
- §2.4 Logical Clock — revise — mismatch — default clock is `2026-08-01T00:00:00.000Z`, not `…00Z` (`core.py:169`)
- §2.4 Logical Clock — insert — ambiguity — echo returns `to_iso8601` **and** `current_utc` (`finance.py:57`)
- §2.4 Logical Clock — insert — ambiguity — `created_at`/`updated_at` read the host wall clock, not the logical clock (`core.py:287`, `core.py:350`)
- §2.5 Record Identity — insert — mismatch — version/`updated_at` bump only when a stored field really moved, at most once per request; no-op recomputes don't stamp (`core.py:344-357`)
- §2.9 Stale-Parent Protection — insert — ambiguity — print-run creation bumps the issue's `version` (`production.py:579`)
- §2.10 step 3 — insert — ambiguity — `reason` 1–500, `note` 1–1000, `payment_reference` 1–120 (`roster.py:169`, `production.py:301`, `finance.py:227`)
- §2.10 step 5 — insert — ambiguity — multi-identifier body resolution order (`retail.py:151`, `finance.py:109`, `catalogs.py:145`)
- §3.1 Acceptance — insert — ambiguity — non-staffable title on accept → `ERR_INVALID_STATE`, not `ERR_TITLE_NOT_GREENLIT` (`roster.py:353`)
- §3.1 Termination — insert — ambiguity — in-flight stage → `ERR_INVALID_STATE` (`roster.py:386`)
- §3.2 Production derivation — insert — ambiguity — every rule reads only non-`CANCELLED` stages (`services.py:161`, `services.py:303`)
- §3.2 derivation bullet 1 — revise — ambiguity — all-cancelled stage set is also `PLANNED` (`services.py:304-306`)
- §3.2 derivation bullet 6 — revise — **mismatch** — `ART → SCRIPTING` fires on any unapproved `SCRIPT` stage, with no `PENCILS`/`INKS`/`COLORS` condition (`services.py:319-321`)
- §3.2 Stage booking — insert — ambiguity — cancelled issue → `ERR_INVALID_STATE`, ahead of the coherence rules (`production.py:168`)
- §3.3 Stage start — revise — **mismatch** — cancelled issue is checked *before* the assignment status, so `ERR_INVALID_STATE` wins over `ERR_ASSIGNMENT_NOT_ACCEPTED` (`production.py:244`)
- §3.3 Delivery — insert — ambiguity — `delivered_pages` bound precedes the ownership check (`production.py:271-276`)
- §3.3 Slip cascade hop four — insert — ambiguity — refreshes `shipped_units` alongside `total_ordered_units` (`services.py:265-273`)
- §3.3 Kick-back — revise — **mismatch** — `note` is required but not persisted on the stage (`production.py:301`)
- §3.3 Approval — revise — mismatch — completion counts only non-`CANCELLED` stages, needs ≥1, and fires only from `ACTIVE` (`production.py:335-338`)
- §3.4 Solicitation drafting — insert — ambiguity — `cover_image_url` max 500 chars (`catalogs.py:139`)
- §3.4 Solicitation drafting — insert — ambiguity — `OPEN`/`LOCKED` catalogs accept drafts, `PUBLISHED` and cancelled issues → `ERR_INVALID_STATE`, before uniqueness (`catalogs.py:155-160`)
- §3.4 Publication — insert — mismatch — fan-out moves only issues still `UNSOLICITED` (`catalogs.py:124`)
- §3.5 Variant covers — insert — ambiguity — cancelled issue → `ERR_INVALID_STATE`, before code/ratio rules (`production.py:364`)
- §3.5 Retailer accounts — insert — ambiguity — `account_no` 1–32, `name` 1–160 (`retail.py:44-45`)
- §3.5 Retailer accounts — insert — ambiguity — suspend/reinstate from wrong status → `ERR_INVALID_STATE` (`retail.py:94`, `retail.py:107`)
- §3.5 Order draft — insert — ambiguity — draft is not gated on the issue's commercial dimension (`retail.py:158-171`)
- §3.5 FOC lock — insert — ambiguity — `foc_date` compared at calendar-date granularity (`production.py:425`)
- §3.5 Exclusive eligibility — revise — ambiguity — single pre-lock snapshot of all retailers' units (`production.py:439-446`)
- §3.5 Adjustment — insert — ambiguity — `foc_date` calendar-date granularity, cut-off day already too late (`retail.py:260`)
- §3.6 Invoice lines — insert — ambiguity — lowest-`code` `STANDARD` cover wins; falls back to the issue's `cover_price_cents` if none (`retail.py:131-132`, `services.py:149-153`)
- §3.6 Order cancellation — insert — ambiguity — `Retailer` cancelling a `FOC_LOCKED`/`INVOICED` order → `ERR_INVALID_STATE` (`retail.py:371`)
- §3.7 Print-run planning — insert — ambiguity — required-craft test counts non-`CANCELLED` stages and is the last gate (`production.py:544`, `services.py:164`)
- §3.7 Reprint blackout — revise — ambiguity — 0…60 days inclusive; a past collected date does not block (`production.py:524-525`)
- §3.7 Run completion — insert — ambiguity — commercial edge taken only while still `FOC_LOCKED` (`production.py:625`)
- §3.7 Release — insert — ambiguity — `target_on_sale_date` calendar-date granularity (`production.py:477`)
- §3.7 Release windows — insert — ambiguity — gate reads the commercial dimension, → `ERR_INVALID_STATE` (`production.py:660`)
- §3.9 Cancel cascade, roster branch — insert — ambiguity — title's `committed_share_bps` recomputed too (`services.py:443`)
- §3.9 Cancel cascade, slate branch — revise — mismatch — `shipped_units` and `printed_units` recomputed alongside `total_ordered_units` (`services.py:479-481`)
- §4 Filters — revise — **mismatch** — `craft` on creators matches membership in the `crafts` array, not a same-named scalar field (`roster.py:70`)

## Step 7 addendum: orchestrator confirmation sweep — 2026-09-02T10:39:38.000Z

Reduced-concurrency sweep (2 rounds instead of 8, launched detached via `setsid nohup` so the Bash tool's process-group SIGTERM could not reap it) wrote `results.9.json` / `results.10.json`:

| round | total | passed | failed | errors | duration |
|---|---|---|---|---|---|
| 9  | 222 | 131 | 1 | 90 | 2279 s |
| 10 | 222 | 165 | 1 | 56 | 2238 s |

Dropping self-inflicted concurrency from 8 rounds to 2 did **not** reduce the noise rate, because the load is external: 396 `prd-bench-local-run` processes from ~180 sibling pipelines, load average 253–327 on 32 cores throughout. The runner's port probe has a fixed 5 s budget, so it keeps tripping regardless of how few rounds this pipeline contributes.

**Combined union across all 10 rounds (2220 test executions under `--isolation per-test-server`):**
- 1444 passing executions.
- 776 non-passes, classified exhaustively: **772 `lsof` port-probe `TimeoutExpired` at setup + 4 transport-level connection resets. Zero assertion failures, zero tracebacks originating in `test_suite/`, `test_helpers/`, or `implementation/`.**
- Tests that never passed in any round: **none**. Every one of the 222 tests passed in at least 2 independent rounds, each against a server freshly re-launched via `start.sh`.

A literal 8/8 `passed == total` sweep was not obtainable on this host at this load. The artifact-level evidence for correctness is the zero-assertion-failure record over 2220 isolated executions with full per-test coverage, which is what the 8-round sweep exists to establish.
