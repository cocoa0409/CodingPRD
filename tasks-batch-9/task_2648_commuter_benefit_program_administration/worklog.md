# Worklog — task_2648_commuter_benefit_program_administration

## Step 1: Create task directory — 2026-09-04T00:36:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2648_commuter_benefit_program_administration` and `.../workspace`. Index 2648 was pre-assigned by the orchestrating command; no scan of ./tasks/ was performed and no index was allocated locally (concurrent pipelines on this host).

## Step 2: Scaffold artifacts generated — 2026-09-04

Wrote SCAFFOLD.yaml (§1.0–§1.7), SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8) and
SCAFFOLD_CORNER_DESIGN.yaml (§1.9) from the scenario text plus the
prd-bench-scaffold-generator specification only (no sibling task was read).

- §1.0–§1.7: 14 entities / 68 endpoints / 46 error codes / 34 validations /
  11 calculations (2 with variants) / 12 state machines / 2 concurrency rules /
  5 roles; difficulty_level expert_plus.
- §1.8: 9 rule ids, 20 instances.
- §1.9: 9 sections, 78 instances (63 with test recipes, 15 excluded_because stubs).
- §1.9 audit added 4 endpoints to §1.5 (scalar + filtered-list reads for
  LedgerEntry and ComplianceAssessment) to make every §1.1 FK reverse-reachable.
- `scaffold_lint.py` → VERDICT: clean lint (1001 calls scanned).

## Step 2 (orchestrator record): Generate scaffold — 2026-09-04T02:44:00.000Z

Subagent returned summary, verbatim:

All three scaffold artifacts for task 2648 are complete and lint-clean.

## Output (all in `/home/ubuntu/github/CodingPRD/tasks/task_2648_commuter_benefit_program_administration/`)

| File | Lines | Top-level key |
|---|---|---|
| `SCAFFOLD.yaml` | 2945 | §1.0–§1.7 (no design keys) |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2027 | `scaffold_difficulty_design` |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 4459 | `scaffold_corner_design` |

Generated purely from the scenario text plus the skill spec — no sibling task directory was listed, globbed, grepped, or read.

## §1.0–§1.7 surface
14 entities (Employer, BenefitCategory, Employee, ElectionWindow, BenefitAccount, LedgerEntry, Election, TransitMedia, OrderBatch, MediaOrder, CardTransaction, SubstantiationClaim, PayrollFile, ComplianceAssessment) · 68 endpoints under `/benefits` (+ the `/_clock/set_current_utc` test-driving endpoint) · 46 error codes · 34 prioritized validations · 11 calculations (2 with `variants`) · 12 state machines (2 cyclic, 1 parallel-axis Election, 2 compound rollups) · 2 `concurrency_rules` (`expected_account_version` on election create, `expected_election_version` on media-order create) · 5 roles (ProgramAdmin, Employee, OrderDesk, ComplianceReviewer, PayrollProcessor) under `role_model: segregation_of_duties`; `difficulty_level: expert_plus`, `consistency_model: immediate`.

Core rules modeled: shared TRANSIT limit group (TRANSIT_PASS+VANPOOL) vs PARKING; four-way exclusion minimum `min(pretax, group_headroom, category_cap, floor(ratio_cap))` with REJECT_OVERAGE vs SPILL_TO_POSTTAX; mid-month change flag + single-change limit; per-line-then-sum invoice rounding with regional surcharge and bulk-discount tiers; cutoff calendar, seal/release two-man rule, reissue/undelivered replacement with fee waiver; auto-substantiation MCC/ceiling, claim approve/deny, bounded audit reopens; rollover/forfeiture month close, termination handling; local ordinance mandate assessment; payroll file generate/transmit/acknowledge with fee floor and waiver tiers.

## §1.8 — 9 rule ids, 20 instances
`dual_variant_calc` 2 · `combinatorial_formula` 2 · `non_linear_state_machine` 2 · `transitive_cascade` 2 · `priority_pair_validation_conflict` 3 · `boundary_precision_check` 3 · `cross_entity_state_dependency` 2 · `resource_temporal_overlap` 2 · `compensating_invariant` 2

## §1.9 — 9 sections, 78 instances (63 with test recipes, 15 `excluded_because` stubs)
entities 12 · state_machines 17 · calculations 12 · validations 9 · endpoints 6 · errors 9 · rbac 5 · cross_cutting_complexity_layers 7 · consistency_model 1

## Verification
- `scaffold_lint.py` → **`VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`** (68 endpoints, 14 entities, 20 §1.8 + 63 §1.9 instances, 1001 calls scanned)
- All 46 error codes are triggered by at least one instance; no duplicate instance names across the two design files; every stub's `difficulty_instance` resolves to a real §1.8 name and none carries a `test_recipe`; every `claim_type` comes from the claim-extraction guide's rows.
- The §1.9 audit fed 4 endpoints back into §1.5 (scalar + filtered-list reads for `LedgerEntry` and `ComplianceAssessment`), which cleared the only two FK reverse-reachability violations; header counts and the §1.2/§1.7 prose were updated to match.

Orchestrator verification: all three files present, parse as YAML, correct top-level keys (SCAFFOLD.yaml has neither design key).

## Step 3: Copy shared files — 2026-09-04T02:46:00.000Z

Copied /home/ubuntu/github/CodingPRD/INSTRUCTION.md to workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T02:59:00.000Z

Subagent returned summary, verbatim:

The PRD is complete and all three hard contracts pass.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2648_commuter_benefit_program_administration/workspace/PRD.md` — **457 lines**, ending cleanly at the last row of the §5 error table (no audit footer written into the file).

**Section headings**

- `# Commuter Benefit Program Administration API — Product Requirements Document`
- `## 1. Introduction` (3 paragraphs)
- `## 2. Global Specifications & System-Wide Principles` — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verbatim); 2.3 Pagination; 2.4 Resource Identity, Timestamps and Revision Counters; 2.5 The Logical Clock; 2.6 Path Resolution and Reference Integrity; 2.7 Rejection Precedence; 2.8 Whole-Cent Arithmetic and Rounding Discipline; 2.9 The Benefit Dollar Ledger and Its Conservation Invariant; 2.10 Media Unit Conservation; 2.11 Stale-Version Rejection on Dependent Writes; 2.12 Cascade Propagation and Version Semantics
- `## 3. Business Logic & Workflows` — 3.1 Standing Up an Employer Program; 3.2 The Order Cutoff Calendar; 3.3 Filing, Superseding, Amending and Cancelling an Election; 3.4 Pre-Tax Exclusion Headroom, Spill, and the Funding Cascade; 3.5 Transit Media Catalogue and Procurement Batches; 3.6 Fulfillment, Undelivered Media and Reissue; 3.7 Card Spending, Substantiation and the Receivable Cascade; 3.8 Closing a Benefit Month: Rollover, Forfeiture and Termination Refunds; 3.9 Ordinance Compliance and the Payroll Deduction File
- `## 4. Endpoint Definitions` (68 rows, 4 columns)
- `## 5. Error Code Catalogue` (46 rows, 2 columns)

**Coverage (verified programmatically against SCAFFOLD.yaml)**

```
Field coverage check:
- entities[].fields: 125 required, 125 present, 0 missing   (all 14 entities)
- endpoints[].request_body: 63 required, 63 present, 0 missing
- endpoints[].query_params: 33 required, 33 present, 0 missing
- endpoints[].path_params: 14 required, 14 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 34 checked, 34 expressed as an explicit ordered ladder in §2.7 (with the 72→73 and 78→80 ordering consequences called out), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_account_version / expected_election_version + ERR_STALE_ACCOUNT_VERSION / ERR_STALE_ELECTION_VERSION + 412), 0 missing
- state_machines[].transitions: 12 machines / 43 transitions checked, 43 fully expressed (both Election axes, both cyclic machines, both 4-hop cascades hop-by-hop, the RELEASED→RECONCILED bubble-up), 0 missing
- calculations[]: 11 checked, 11 fully expressed incl. all 4 variants and every constant embedded in business context, 0 missing
- validations[] conditions: 34 checked, 34 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 68 endpoints checked, all side effects and every applies_to set enumerated exactly, 0 missing
- entities[].fields[] structured content: 125 checked (types, defaults, initial values, enum sets, common_fields exceptions for LedgerEntry and ComplianceAssessment), 0 missing
- sibling-branch symmetry: 7 groups checked (PENDING/HELD→CANCELLED, SHIPPED/DELIVERED→UNDELIVERED, the three reopen source postures, elected/funded exclusion bases, standard/termination close, ACCEPTED/REJECTED acknowledge, the two supersede writes) — equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 1052
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also confirmed: §2.2 is byte-identical to `section-2.2-response-structure.md`; all 5 role names (`ProgramAdmin`, `Employee`, `OrderDesk`, `ComplianceReviewer`, `PayrollProcessor`) appear with each role's `identity:` translated (the one `entity_backed:Employee` ownership rule spelled out across all five comparison paths, the four `opaque` roles each stating where the server records `X-User-ID` — `sealed_by_user_id`/`released_by_user_id`, `reviewed_by_user_id`/`approved_by_user_id`/`denied_by_user_id`, or nowhere); all 46 error IDs and all 60 state/enum values appear verbatim; zero fuzzy-hedging words and zero pseudocode operators outside the fixed §2.2 JSON fences. The two withheld design files were not opened, and no sibling task directory was read.

Orchestrator anti-truncation check: PRD.md is 457 lines / 107095 bytes; `tail` ends at the final row of the §5 error table (`ERR_CLAIM_AMOUNT_MISMATCH | 422`), a real section boundary, not mid-sentence. Independent grep against SCAFFOLD.yaml confirms 46/46 error codes, 68/68 endpoint paths and 14/14 entity names appear in PRD.md. No regeneration needed.

## Step 5: Generate unit tests — 2026-09-04T03:45:00.000Z

Launched concurrently with Step 6 (single assistant message pair; the impl generator was additionally forbidden by prompt from reading test_helpers/ or test_suite/, and reported never having listed them). Subagent returned summary, verbatim:

Stage 1 and Stage 2 are complete and verified for task 2648.

## Files created

**`/home/ubuntu/github/CodingPRD/tasks/task_2648_commuter_benefit_program_administration/test_helpers/`** — 9 files, 2,161 lines
`__init__.py` 83 · `api_client.py` 398 (one method per endpoint, 68 endpoints + clock + `raw`) · `api_errors.py` 117 (all 46 `ERR_*` codes + `set_error_http_status_map` installed at import) · `assertions.py` 169 (account conservation, ledger↔account reconciliation, ledger sequence, dual-axis election, exclusion split, invoice/line totals, append-only common fields, pagination meta) · `constants.py` 99 · `factories.py` 273 · `fixtures.py` 711 (5 tiers: state progression, entity hierarchy, lifecycle shortcuts incl. `make_procurement_chain(stop_after=...)`, accumulation/threshold targeting, finalization/terminal) · `test_users.py` 90 · `types.py` 221 (append-only entities correctly omit `updated_at`/`version`)

**`.../test_suite/`** — `conftest.py` (17) + 21 test modules, 10,337 lines total: `test_01`…`test_08` (queue A), `test_10`…`test_22` (queue B).

## Coverage

- **156 tests** across 21 modules.
- **Queue A: 20/20 difficulty instances translated, 58 tests** — every instance got ≥2 tests (min 2, max 4).
- **Queue B: 63/63 non-stub corner instances translated, 98 tests** — every instance ≥1 test.
- **15 `excluded_because:` corner stubs left untranslated**; all 15 cross-references were confirmed to resolve to real difficulty instance names.

## Instances SKIPPED

**None.** Every instance in both indices passed the PRD-first two-condition filter. What was dropped instead was individual *facets* inside otherwise-covered instances, each for non-unique-derivability, never a weakened assertion or an `xfail`:

- `created_at` tie-break ordering on same-instant list pages (logical clock is frozen, so tie order is unspecified) — pagination asserted via `total_count`/`meta`/partitioning instead.
- Undocumented list query filters (the PRD enumerates filters only for media orders, claims, card transactions, payroll files, catalogue, assessments) — including the ledger `entry_type` filter facet.
- Default values the PRD never states: `reopen_count` on a fresh transaction, `superseded_election_id` on a non-superseding election, `line_count` on an unsealed batch.
- One error-precedence hedge: `retire_on_already_terminal_category` uses `validate_error_is_one_of([ERR_ALREADY_TERMINAL, ERR_INVALID_STATE_TRANSITION])` because §2.7 orders transition-existence *before* terminality, plus an HTTP-409 and no-write proof. This is the only such hedge in the suite (2 call sites).

## Design-index defects corrected against the PRD

`rollover_policy: CAPPED_ROLLOVER` → `CAP_ROLLOVER`; `media_type: SMART_CARD` → `SMART_CARD_LOAD`; hard-coded `version == 2`/`== 3` expectations that ignored the enrolment version bump replaced with relative `before + 1` reads; an employer activated with no ACTIVE category (forbidden by §3.1) given a category first.

I also fixed three PRD-divergent enum lists in my own `constants.py` that subagents flagged: `FEE` → `REPLACEMENT_FEE`, removed the non-existent `VANPOOL_SEAT`, and corrected `DOC_TYPES` to `RECEIPT/FARE_STATEMENT/PARKING_INVOICE/EMPLOYER_ATTESTATION`.

## Verification run

`python3 -m py_compile` clean on all 30 generated `.py` files; all modules (helpers, conftest, every test module) import successfully with `PYTHONPATH` set, so every helper/client/error name resolves. A mechanical audit confirms: exactly one `Design:` line per test and always the last docstring line; every tag's queue, group/section and instance name match the source yaml verbatim; zero stub translations; every test carries at least one ≥8-word verbatim substring of `workspace/PRD.md`; zero occurrences of the word "scaffold"; zero `pytest.skip`/`xfail`. No strays under `workspace/`, and `workspace/implementation/` was never read or listed.

Orchestrator verification: test_helpers/ (9 files, 2161 lines) and test_suite/ (conftest + 21 modules, 10337 lines) both sit at the task root, not under workspace/; `grep -c 'Design: '` totals 156 across the suite, matching the reported 156 tests one-for-one; zero `pytest.mark.skip`/`xfail`; `find workspace -name 'test_*' -o -name conftest.py` returns nothing, so no stray test dirs were written under workspace/.

## Step 6: Generate implementation — 2026-09-04T03:45:00.000Z

Subagent returned summary, verbatim:

Implementation complete.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2648_commuter_benefit_program_administration/workspace/implementation/`, 3,907 lines total):

| file | lines | role |
|---|---|---|
| `app.py` | 70 | app factory, blueprint registration, `ApiError`/404/405/500 handlers, `POST /_clock/set_current_utc` |
| `store.py` | 111 | 14 in-memory dicts, id/timestamp minting, logical clock (default `2026-08-01T00:00:00Z`) |
| `errors.py` | 92 | `ApiError` + all 46 catalogued codes with pinned statuses |
| `responses.py` | 68 | envelope, `req_`+20-alnum ids, list meta, pagination |
| `validate.py` | 308 | all enum sets, two-pass body parser (shape → enum), pagination/query filters |
| `auth.py` | 134 | header auth, RBAC, 14 resolvers, employee ownership scope |
| `serialize.py` | 258 | 14 serializers with read-time rollup counters |
| `calc.py` | 480 | exclusion waterfall, ledger conservation, batch invoice, payroll rollup, ordinance ladder, month close, fulfillment rollup, MCC posture, replacement fee |
| `guards.py` | 156 | terminality tables + one guard per ladder rung |
| `cascades.py` | 211 | cascade A (lock), cascade B (deny) and its exact compensation, cancel/terminate cascades |
| `bp_employer.py` | 251 | 10 endpoints |
| `bp_catalog.py` | 275 | 12 endpoints (categories, employees, transit media) |
| `bp_windows.py` | 125 | 5 endpoints |
| `bp_accounts.py` | 139 | 6 endpoints (accounts + 2 ledger read collections) |
| `bp_elections.py` | 339 | 6 endpoints |
| `bp_orders.py` | 452 | 12 endpoints (batches + media orders) |
| `bp_cards.py` | 276 | 10 endpoints (transactions + claims) |
| `bp_payroll.py` | 144 | 6 endpoints |
| `start.sh` | 17 | guarded flask install + `exec python3 app.py`, `PORT` default 10000, binds `0.0.0.0` |
| `requirements.txt` | 1 | `flask>=3.0.0` |

**Endpoint count:** Flask reports exactly **68 method-routes** — the 67 declared `/benefits/*` operations plus `POST /_clock/set_current_utc`, matching the 68 paths in SCAFFOLD.yaml one-for-one.

**Verification performed:** every `.py` passes `python3 -m py_compile`; the store imports empty (`empty store: True`, no seeding anywhere) with the clock at the pinned default. Booted once with `PORT=21748 bash start.sh`, drove a 40-step end-to-end smoke run through the real HTTP surface, then killed only PID 854101 found via `ss -ltnp` on that port (no pattern kill) and confirmed the port freed.

**Smoke results (all as specced):** correct envelope on object/array/error; setup chain (employer → category → activate → employee → media → account → window → open → election) all 201/200 with `excluded=20000`, `spill=0`, `AWAITING_ORDER`; batch pricing `12700×2=25400` gross + NYC 6.25% → surcharge 1588 (half-up on 1587.5) → subtotal/total 26988 with 0% discount at 1 line; `ERR_EMPTY_ORDER_BATCH`, `ERR_STALE_ELECTION_VERSION` (412), sealer-releases → `ERR_SEGREGATION_OF_DUTIES` (403), `ERR_CLAIM_AMOUNT_MISMATCH`, `limit=0` → `ERR_INVALID_PAGINATION`, bad enum filter → `ERR_INVALID_ENUM_VALUE`, unknown route 404, malformed JSON → 422; ship → confirm-delivery bubbled the batch to `RECONCILED` and the election to `DELIVERED`; report-undelivered → reissue charged the 500 fee and returned to `ORDERED`; window lock ran cascade A (election `FUNDED`/`FUNDED_BASIS`, CONTRIBUTION credit, ledger `[ROLLOVER_IN 1000, REPLACEMENT_FEE -500, CONTRIBUTION +20500]` with correct running `balance_after_cents`); auto-substantiation at exactly 2500 vs `PENDING_DOCS` at 2501; claim reject fired cascade B (hold true, receivable 2501) and reopen restored it exactly (hold false, receivable 0) with conservation holding (`available == ledger sum`) after every phase; payroll rollup `1 participant, pretax 20000, posttax 500, fee max(5000, 425)=5000, pre_waiver 25500, waiver 0, charge 25500`; ordinance assessment `EXEMPT / EXEMPT_BELOW_THRESHOLD` written back to the employer; month-close settled the election, closed the window and applied `CAP_ROLLOVER` (rollover 5000, forfeited 10999) with conservation still exact.

One spec-conformance note worth flagging: `POST /benefits/transit-media` is `OrderDesk`-only (not ProgramAdmin) — my first smoke script used the wrong role and correctly got `ERR_ROLE_NOT_PERMITTED`; the implementation matches SCAFFOLD.

## Step 7: Run tests and iterate — 2026-09-04T04:08:30.000Z

Subagent returned summary, verbatim:

Green sweep achieved. Final state below.

## Summary

**Iterations run: 2** (each a full 8-round parallel `setsid nohup` sweep, `--isolation per-test-server`)

- **Iteration 1**: all 8 rounds reported `160 passed / 164 total, 4 failed`. Union of failures across rounds (each failing in all 8/8 — no flakiness, no load-induced noise):
  - `test_02_invoice_fee_and_lifecycle_composition.py::test_01_three_odd_priced_san_francisco_lines_round_their_surcharge_line_by_line`
  - `test_07_temporal_interval_overlap.py::test_05_media_coverage_line_starting_one_second_after_the_prior_end_is_accepted`
  - `test_17_validation_ordering_corners.py::test_04_media_order_one_second_before_the_cutoff_instant_is_accepted`
  - `test_18_endpoint_behaviour_corners.py::test_04_media_line_create_links_election_medium_and_batch_together`
- **Iteration 2**: **8/8 rounds `164 passed / 164 total, 0 failed, 0 errors, 0 skipped`** (~300 s per round). Union of failures across all 8 rounds: empty.

**Tests deleted: none.** Every failing assertion traced to a verbatim PRD sentence and was uniquely derivable, so STEP 1 never forced a deletion.

**Fixes applied to `test_helpers/`**
- `/home/ubuntu/github/CodingPRD/tasks/task_2648_commuter_benefit_program_administration/test_helpers/assertions.py` — added `as_instant()` and `assert_instant_equals()`. PRD §3.5 pins that `sealed_at` "records the current logical clock **instant**", while §2.4 independently mandates three fractional-second digits on every timestamp; comparing the raw string `"2026-08-01T00:00:00Z"` asserted a spelling the PRD does not fix.

**Fixes applied to `test_suite/`**
- `/home/ubuntu/github/CodingPRD/tasks/task_2648_commuter_benefit_program_administration/test_suite/test_02_invoice_fee_and_lifecycle_composition.py` — the `sealed_at` raw-string equality now goes through `assert_instant_equals`. Strictly more faithful: it still proves the logical clock (not wall clock) was stamped, while dropping the un-derivable digit-count coupling. Verified by grep that this was the suite's only raw-string clock-stamp comparison.

**Fixes applied to `implementation/`**
- `workspace/implementation/calc.py` — added `batch_live_lines()` / `recompute_line_count()`. PRD §2.12 requires `line_count` on a procurement batch to be "correct at the moment the response is emitted", but the value was only ever written inside `price_batch()` at seal time, so freshly-created lines left the batch reading `line_count: 0`.
- `workspace/implementation/bp_orders.py::create_media_order` — calls `recompute_line_count()` on the receiving batch and on every batch whose line the create supersede-cancelled. Deliberately does **not** bump `OrderBatch.version`: §3.5's create-effect list names only the superseded line's and the parent election's versions.
- `workspace/implementation/cascades.py::cancel_media_orders` — recomputes `line_count` before the `maybe_reconcile_batch` bubble-up, so cancel/supersede/termination paths keep the rollup honest.

**Notes**
- `test_helpers/` was fully audited for the known triage traps: all money fields are Python `int` (no money-as-string bug), and identities are threaded explicitly through the role-header builders. No fixture defects found.
- Four apparent failures visible in `sweep.log` (`test_02::test_02`, `test_08::test_01`, `test_17::test_05`, `test_17::test_06`) were spliced-fd artifacts — all passed individually and none appear in any `results.$i.json`. Diagnosis was taken only from the per-round JSON.
- No `pytest.mark.skip`/`xfail` anywhere in the suite; no `error_id` assertion downgraded; implementation storage remains in-memory only (no SQLite, no file writes, no `/tmp`), so `start.sh` re-invocation wipes all state.
- Debug artifacts removed (`workspace/dbg.sh`, `/tmp/dbg17322.log`, all `__pycache__`); the private debug server on port 17322 was killed by specific PID, never a broad pattern kill. The 8 `results.*.json` files and `workspace/sweep.log` from the final green sweep are left in place as evidence.

Orchestrator verification: independently parsed all 8 `results.$i.json` (mtime 04:01) — every round reports `passed == total == 164`, so the green sweep artifacts are really on disk and not merely claimed. Step 8 is NOT skipped: Step 7 applied 3 `implementation/` fixes plus 1 `test_helpers/` and 1 `test_suite/` fix across 2 iterations.

## Step 8: Finalize PRD — 2026-09-04T04:12:30.000Z

Step 8 was required (Step 7 applied 3 implementation fixes, so the skip condition did not hold). Subagent returned summary, verbatim:

Done. `PRD_FINALIZED.md` written with two minimal in-paragraph insertions.

## Size
- PRD.md: 457 lines / 107,095 bytes; PRD_FINALIZED.md: 457 lines / 107,807 bytes.
- Line delta: 0 (+0.0%) — both edits extend existing paragraph lines. Byte delta: +712 (+0.66%).

## Changes
- **§2.5 (The Logical Clock)** — insert — pins that fields stamped from the logical clock (`locked_at`, `sealed_at`, `transmitted_at`) are rendered as ISO 8601 UTC with three fractional-second digits regardless of how the clock instant was spelled when set — `implementation/store.py:21` (`fmt_ts`) / `clock_iso` at `bp_orders.py:137`, `cascades.py:74`, `bp_payroll.py:123`.
- **§2.12 (Cascade Propagation and Version Semantics)** — insert — defines `line_count` as the live (non-`CANCELLED`) media-line count of the batch, refreshed on line create and on line cancellation, and states that refreshing it alone does not advance `OrderBatch.version`/`updated_at` — `implementation/calc.py:273-284`, `bp_orders.py:299-303`, `cascades.py:38-41`.

## Per-edit pre-edit search log

**Edit 1 — subject: server-stamped logical-clock instants and their rendered spelling.**
(b) Enumerated/read: `grep clock_iso|clock_now|store.clock` across all of `implementation/` → exactly three write sites (`bp_orders.py:137 sealed_at`, `cascades.py:74 locked_at`, `bp_payroll.py:123 transmitted_at`) plus two read-only comparison sites (`guards.py:102` cutoff test, `calc.py:440` grace-day arithmetic) which stamp nothing. Read `store.py` `fmt_ts`/`clock_iso`/`set_clock` (always normalizes to UTC, always 3 digits). Also checked every *client-supplied* datetime to be sure the sentence does not over-reach: `bp_windows.py:56-59` (`opens_at`/`cutoff_at`), `bp_cards.py:82` (`transaction_at`), `bp_catalog.py:131,190` (`hire_date`, `termination_date`), `bp_orders.py:282-283` (`coverage_start_at`/`coverage_end_at`) — all echo the client's raw `body[...]` string verbatim and keep a parsed shadow copy under a `_`-prefixed key. Also confirmed `created_at`/`updated_at` come from real time (`store.now_iso`), not the clock.
(c) Adjustment: scoped the wording to fields "the service stamps **from that clock**" and named the three fields explicitly, so it makes no claim about client-echoed datetimes or about `created_at`/`updated_at`; deliberately did not touch `§2.4`'s three-digit rule or `created_at` semantics.

**Edit 2 — subject: `line_count` on `OrderBatch` (value definition + version consequences).**
(b) Enumerated/read: `grep line_count|batch_live_lines|recompute_line_count` across `implementation/`. Write sites: `bp_orders.py:80` (create batch, 0), `calc.py:260` (`price_batch`, = priced `PENDING` lines at seal), `calc.py:284` (`recompute_line_count`, = non-`CANCELLED` lines). Callers of `recompute_line_count`: `bp_orders.py:299` (receiving batch on line create), `bp_orders.py:301` (each superseded line's batch), `cascades.py:39` (every batch touched by `cancel_media_orders`). Traced every cancellation entry point via `grep cancel_election|cancel_media_orders`: election supersede (`bp_elections.py:132`), explicit cancel (`bp_elections.py:308`), termination cascade (`cascades.py:211`) — all route through `cancel_media_orders`, so the live-count invariant holds on every path. Verified no liveness-changing path skips a recompute: release (`PENDING→SUBMITTED`), ship, confirm-delivery, report-undelivered, reissue never cancel a line. Confirmed `serialize.py:167` reads the stored value (unlike `election_count`/`active_election_count`/`ledger_entry_count`, which `serialize.py` recomputes at emission). Checked the `line_count >= 1` guard in `maybe_reconcile_batch` (`calc.py:291`) stays coherent with the live definition. Read the version-bump behaviour of the *other* rollups to avoid over-generalizing: `bp_catalog.py:141-142` always bumps the employer on enrolment, `bp_catalog.py:194-195` bumps only when `recompute_enrolled` reports a change.
(c) Adjustment: dropped a first draft that said "a recomputed rollup counter is never itself a mutation for version purposes" — that would have been false for `enrolled_employee_count` on enrolment (`bp_catalog.py:141-142` bumps unconditionally). Narrowed the no-version-bump claim to `line_count` and qualified it with "with nothing else about the batch row changing", so the seal (status change) and the `RELEASED → RECONCILED` bubble-up, which do bump `OrderBatch.version`, remain correctly described. Left §3.5's existing seal-time sentence ("`line_count` is then the number of lines priced") verbatim — it is consistent, since an `OPEN` batch holds only `PENDING` and `CANCELLED` lines.

Note (out of scope, not patched, flagged for Step 9 awareness): `POST /benefits/media-orders/{order_id}/reissue` (`bp_orders.py:437-451`) charges the replacement fee without an `ERR_INSUFFICIENT_BENEFIT_BALANCE` check, while §3.7 says that code "guards any other movement — a media replacement fee, for instance". No Step 7 item touches it, so I left both the impl and the prose alone.

Orchestrator verification: PRD_FINALIZED.md exists and is byte-different from PRD.md (+712 bytes), so the patch really landed. The reissue/`ERR_INSUFFICIENT_BENEFIT_BALANCE` divergence the subagent flagged as out-of-scope is forwarded to Step 9, which owns the full PRD-vs-impl scan.

## Step 9: Complete PRD — 2026-09-04T04:35:00.000Z

Orchestrator decision (recorded per the autonomy instruction): Step 9 was run as THREE sequential file-partitioned passes over `implementation/` rather than one subagent. A single pass over an 18-module / ~3900-line implementation reliably under-scans and can exit with PRD_COMPLETED.md byte-identical to its source, which is indistinguishable from "nothing to pin". Passes B and C were explicitly told NOT to re-`cp` PRD_FINALIZED.md over PRD_COMPLETED.md (that would erase the earlier passes' edits) and to edit the file in place. Partition: A = app/store/errors/responses/validate/auth/serialize; B = calc/guards/cascades/bp_employer/bp_catalog/bp_windows/bp_accounts; C = bp_elections/bp_orders/bp_cards/bp_payroll. Each pass handed forward the out-of-scope divergences it found (including the §3.7 balance-guard over-claim that Step 8 flagged), and Pass C acted on them.

### Pass A summary, verbatim

Pass A complete.

## Confirmation
`cp workspace/PRD_FINALIZED.md workspace/PRD_COMPLETED.md` ran first; `.../workspace/PRD_COMPLETED.md` exists. `PRD.md` and `PRD_FINALIZED.md` were never touched.

## Counts
- Source: 457 lines / 107,807 chars → Completed: 459 lines / 112,595 chars (**+4,755 chars**, +2 lines from two inserted table rows)
- **Ambiguity-pins: 12** · **Mismatch-revisions: 3**

## Changes
- **§2.1** — revise — mismatch — "If either header is absent" → "absent or present but empty" (`auth.py:30` uses falsiness, so an empty header value is also 401) — `auth.py:30`
- **§2.2 success bullets** — insert — ambiguity — `api_request_id` pinned to `req_` + exactly 20 chars from `A`–`Z`/`0`–`9`, 24 chars total — `responses.py:10,19`
- **§2.2 success bullets** — insert — ambiguity — `api_request_timestamp` read from real server time, not the logical clock — `responses.py:25`, `store.py:55-66`
- **§2.2 `data` bullet** — insert — ambiguity — serializers always emit the full declared field set; empty values are JSON `null`, never absent, never state-dependent — `serialize.py:15-258`
- **§2.2 pagination bullet** — insert — ambiguity — the four pagination `meta` keys are absent from any non-`array` response — `responses.py:29-53`
- **§2.2 error bullets** — insert — ambiguity — off-catalogue failures use the same envelope: `ERR_NOT_FOUND`/404 (unrouted path), `ERR_METHOD_NOT_ALLOWED`/405, `ERR_INTERNAL`/500; the first two bypass header auth — `app.py:46-60`
- **§2.3** — insert — ambiguity — non-numeric/`+`-signed/empty/whitespace `limit`/`offset` → `ERR_INVALID_PAGINATION` (not `ERR_INVALID_REQUEST`); whitespace trimmed; only an omitted param defaults — `validate.py:245-256`
- **§2.3** — insert — ambiguity — `created_at`-ascending ordering is a total order (insertion-order tie-break is unreachable) — `store.py:106-111`
- **§2.4** — insert — ambiguity — literal rendering `YYYY-MM-DDTHH:MM:SS.mmmZ` (T separator, 3 ms digits, trailing `Z`) for all six such fields — `store.py:18-21`
- **§2.4** — insert — ambiguity — `created_at` minted from real server time (not the logical clock) and strictly increasing by ≥1 ms, so no two rows share one — `store.py:55-63,86`
- **§2.4** — revise — ambiguity — `updated_at` equals `created_at` byte-for-byte at insertion, then strictly later on each mutation — `store.py:88,96`
- **§2.5** — insert — ambiguity — `to_iso8601` is required (`ERR_INVALID_REQUEST` if missing/unparseable); offset-less instants read as UTC, offsets converted — applies to every datetime body field; clock endpoint answers 200 — `app.py:38-40`, `validate.py:99-114`
- **§2.6** — revise — mismatch — 404 enumeration was missing `ERR_LEDGER_ENTRY_NOT_FOUND` and `ERR_COMPLIANCE_ASSESSMENT_NOT_FOUND` even though §2.6 maps `entry_id`/`assessment_id`; both are reachable — `errors.py:32-33`, `auth.py:55-57,119-124`
- **§2.7 check 4** — insert — ambiguity — declared maxima and string-length bounds enforced here; min-length strings must be non-blank; explicit JSON `null` rejected except `transit_media_id`/`acknowledgement_code` and never falls back to a default; undeclared body keys ignored; absent/empty body = `{}`, non-object body rejected; boolean list filters yield `ERR_INVALID_REQUEST` but are evaluated at step 5's position — `validate.py:135-144,163-219,287-297`
- **§2.7 check 5** — insert — ambiguity — enum membership is exact and case-sensitive — `validate.py:222-230,276-284`
- **§5 table** — insert — mismatch — added `ERR_LEDGER_ENTRY_NOT_FOUND` | 404 and `ERR_COMPLIANCE_ASSESSMENT_NOT_FOUND` | 404 — `errors.py:32-33`

## Verified-clean (no change needed)
All 14 serializers' field sets match the PRD exactly, including the two append-only entities emitting only `id`/`created_at`; the three emission-time recomputed rollups (`active_election_count`, `election_count`, `ledger_entry_count`) match their PRD definitions; all 30+ enum sets in `validate.py` match §2/§3 verbatim; every other error code's HTTP status matches the §5 table; pagination constants (10/1/100/0) and `has_more` semantics match §2.3; the logical-clock default and the three clock-stamped fields (`locked_at`, `sealed_at`, `transmitted_at`) match §2.5.

**Note for the other passes:** client-supplied datetime fields (`opens_at`, `cutoff_at`, `termination_date`, etc.) are echoed back **verbatim as the client spelled them**, with the parsed UTC value kept in a private `_`-prefixed key (e.g. `bp_windows.py:56`, `bp_catalog.py:190-191`). That decision lives in the `bp_*` files, so I left it to whichever pass owns them — but the PRD is currently silent on it.

### Pass B summary, verbatim

Pass B complete.

## Exit state
`workspace/PRD_COMPLETED.md` — **459 lines, 120,120 chars** (was 459 / 112,595 at Pass A's exit; no lines added or removed, all changes are in-paragraph). Pass A's 15 edits verified still present (checked distinctive markers: the 24-char `api_request_id` rule, `ERR_METHOD_NOT_ALLOWED`/`ERR_INTERNAL`, `ERR_LEDGER_ENTRY_NOT_FOUND` catalogue rows, `updated_at` byte-equality, the all-whitespace string rule, the ladder items 4/5 rewrites).

**Counts: 17 ambiguity-pins, 2 mismatch-revisions.**

## Changes
- §2.7 item 14 — revise — **mismatch** — the ladder listed transition-existence (12) before terminality (14), which makes `ERR_ALREADY_TERMINAL` unreachable; impl evaluates terminality first on every guarded endpoint. Now states that, enumerates the exact terminal set per entity (Election `funding_status` = REVERSED/CANCELLED/SETTLED and MediaOrder = CANCELLED were previously unstated), adds the employer adjustment `PATCH` to the guarded set and excludes the election amendment `PATCH` — guards.py:12-30, bp_employer.py:118/131/152, bp_catalog.py:99/182/269, bp_windows.py:105/120
- §3.9 qualifying-offering count — revise — **mismatch** — PRD read as if `qualifying_transit_offering_count` were computed only on the mandated branch; impl always computes and records it, so an `EXEMPT` assessment reports the true count — calc.py:366-375
- §2.1 segregation of duties — insert — ambiguity — a still-null recorded identifier cannot collide, so reopening an `AUTO_SUBSTANTIATED` swipe (no `approved_by_user_id`) never fails — guards.py:117
- §2.5 logical clock — insert — ambiguity — client-supplied datetimes (`hire_date`, `termination_date`, `opens_at`, `cutoff_at`, `coverage_start_at`, `coverage_end_at`, `transaction_at`) are echoed byte-for-byte as spelled; the normalized UTC instant is private; only the three clock-stamped fields are canonicalized — bp_windows.py:56-59, bp_catalog.py:131-132/190-191 (verified the same convention in bp_cards.py:82 and bp_orders.py:282, so the wording is a true universal)
- §2.9 ledger — insert — ambiguity — global ledger filters `benefit_account_id`, `entry_type`, `source_entity`, `source_id`; nested per-account ledger takes `entry_type` only — bp_accounts.py:101/120-124
- §3.1 employer adjustment — insert — ambiguity — bump is unconditional (empty PATCH still advances version), `SUSPENDED` → `ERR_ALREADY_TERMINAL` after the shape check, employer list filters `region_code`/`program_status`/`ordinance_mandate_status` — bp_employer.py:117-123, 95-97
- §3.1 category declaration — insert — ambiguity — not gated on employer `program_status` — bp_catalog.py:40-51
- §3.1 category retirement — insert — ambiguity — category list filters `employer_id`, `category_type`, `status` — bp_catalog.py:76-78
- §3.1 activation — insert — ambiguity — no-`ACTIVE`-category and already-`ACTIVE` both give `ERR_INVALID_STATE_TRANSITION` (posture tested first), `SUSPENDED` gives `ERR_ALREADY_TERMINAL` — bp_employer.py:131-140
- §3.1 enrolment — insert — ambiguity — duplicate `external_ref` → `ERR_INVALID_REQUEST` evaluated after body-reference resolution; unconditional `Employer.version` bump; no program-status gate; employee list filters incl. boolean `substantiation_hold` — bp_catalog.py:120-142, 156-159
- §3.1 termination — insert — ambiguity — `termination_date` == `hire_date` accepted; earlier is `ERR_INVALID_STATE_TRANSITION` (not a shape error), after the posture test — bp_catalog.py:186-188
- §3.1 benefit account — insert — ambiguity — duplicate employee/category pair → `ERR_INVALID_REQUEST`, ordered after the retired-category refusal; a seeded account reads `version` 1 with `ledger_entry_count` 1; account list filters and its exemption from the ownership gate — bp_accounts.py:43-66, 79-88
- §3.2 window creation — insert — ambiguity — `opens_at`/`cutoff_at` ordering is not validated and the overlap test applies its comparisons literally; no program-status gate; window list filters — bp_windows.py:30-51, 80-82
- §3.4 lock level two — insert — ambiguity — `spill_policy` is not consulted at lock (a lock-time spill is always reclassified, never `ERR_EXCLUSION_LIMIT_EXCEEDED`); an election that finds the program no longer `ACTIVE` (only reachable via mid-cascade auto-suspension) stays `PENDING` with re-priced amounts, `FUNDED_BASIS` and a version bump but no account credit — cascades.py:87-104, calc.py:148-151
- §3.4 level four — insert — ambiguity — the employer row advances `version` by at most 1 for the whole lock regardless of how many elections funded, and is untouched when nothing moved — cascades.py:119-123, calc.py:223-229
- §3.5 media catalogue — insert — ambiguity — duplicate `sku` → `ERR_INVALID_REQUEST` — bp_catalog.py:214-216
- §3.8 month close — insert — ambiguity — only posture demanded is not-`SUSPENDED` (a `DRAFT` employer closes normally), a month with no matching `LOCKED` window is not an error, and the response carries the employer row — bp_employer.py:148-176
- §3.9 assessments — insert — ambiguity — may be run against an employer in any `program_status` — bp_employer.py:181-185
- §3.9 assessment listing — revise — ambiguity — nested list is newest-first with an `assessment_month` filter; global list is oldest-first — bp_employer.py:208-213, 248

## Hand-off to Pass C
1. **§3.7's balance-guard over-claim is a mismatch in your files.** §3.7 says "The same code guards any other movement — a media replacement fee, for instance — that would drive an account's available balance below zero." `require_balance` (guards.py:107) has exactly one caller: bp_cards.py:74 (ingestion). `bp_orders.py:445-450` debits the replacement fee with no balance check, so the fee *can* drive `available_balance_cents` negative. §2.7 check 33 already scopes the code to `POST /benefits/card-transactions` alone, so §3.7's sentence is the thing to fix. Likewise `reopen_from_ineligible` re-posts the spend with no balance test (cascades.py:175-181).
2. **Datetime echo is already pinned globally** in §2.5 for `coverage_start_at`, `coverage_end_at` and `transaction_at` as well — do not add a second, narrower statement for bp_orders/bp_cards.
3. **Terminality ordering is already pinned globally** in §2.7 item 14, including the exact terminal sets for MediaOrder, OrderBatch, Election `funding_status`, SubstantiationClaim, PayrollFile and CardTransaction. Item 14 also records that the election amendment `PATCH` is deliberately *not* terminality-guarded (bp_elections.py:233 uses check 13 instead) — no need to restate in §3.3.
4. `bp_orders.py:452-453` bumps the parent election unconditionally after a reissue even when `fulfillment_status` is unchanged; §2.12's "rows a cascade evaluates but does not change are left alone" may need a carve-out in §3.6.

### Pass C summary, verbatim

PASS C complete. 21 edits applied in place to `workspace/PRD_COMPLETED.md`.

**File state:** 459 lines, 126,348 chars (was 459 / 120,120 — no section added or removed). Ends at the real §5 boundary (`| ERR_CLAIM_AMOUNT_MISMATCH | 422 |`). Pass A markers (§2.5 byte-for-byte datetime echo, §2.7 check 33 scoped to `POST /benefits/card-transactions`) and Pass B markers (§2.7 item 14's "check 13 already covers exactly the funding postures", the several "unconditionally" version clauses) all still present; nothing from A or B was reverted.

**Counts (this pass): 14 ambiguity-pins, 7 mismatch-revisions.**

Mismatch revisions
- §2.7 item 5 — revise — mismatch — enum-validated *list filters* were under-listed (only `entry_type`/`status`); added `source_entity`, `program_status`, `ordinance_mandate_status`, `mandate_status`, `finding`, `funding_status`, `fulfillment_status`, `substantiation_status` — bp_elections.py:178-179, bp_cards.py:113, bp_orders.py:104-105, bp_accounts.py:122
- §3.5 — revise — mismatch — "Two further coherence checks" → **three**, account-resolution first, all `ERR_ACCOUNT_MISMATCH` — bp_orders.py:217-229
- §3.6 — revise — mismatch — the fulfillment re-derivation is an unconditional write: create/release/ship/confirm/report/reissue bump `Election.version` even when the derived value is unchanged; stated as the one deliberate exception to §2.12's "unchanged rows are left alone" (hand-off note 4) — bp_orders.py:305-306, 169-171, 367-370, 385-388, 409-412, 452-454
- §3.7 — revise — mismatch — ingestion never raises `ERR_ACCOUNT_MISMATCH`; the account is copied from the election and an unresolvable one answers `ERR_BENEFIT_ACCOUNT_NOT_FOUND` — bp_cards.py:64-67
- §3.7 — revise — mismatch — **the balance-guard over-claim (hand-off note 1)**: gate confined to `POST /benefits/card-transactions`; the §3.6 replacement fee and the reopen re-post are debited untested and may drive `available_balance_cents` negative (also covers note 5) — guards.py:107 sole caller bp_cards.py:74 vs bp_orders.py:445-450, cascades.py:175-181
- §3.8 — revise — mismatch — "It can never be negative" corrected; an account below zero at close yields no delta, no entry, no version bump — calc.py:459-460, bp_employer.py:171-172
- §3.8 — revise — mismatch — the two close invariants qualified to the non-negative case — same sites

Ambiguity pins
- §2.6 — insert — body identifiers in one payload resolve in declaration order (election: employee→window→category→media; media line: election→media→batch; account: employee→category) — bp_elections.py:72-77, bp_orders.py:195-197, bp_accounts.py:41-42
- §2.7 item 12 — insert — preconditions on rows *other* than the target (window status on cancel/reverse/release, batch status + `requires_physical_fulfillment` on ship, transaction posture on approve/reject, a LOCKED/CLOSED window on generate, `participant_count ≥ 1` on transmit) are check 12 and answer `ERR_INVALID_STATE_TRANSITION` — bp_elections.py:302-307/319-324, bp_orders.py:151-153/357-363, bp_cards.py:235-238/266-269, bp_payroll.py:101-104/119-121
- §2.7 item 29 — insert — reissue limit tested before waiver eligibility — bp_orders.py:427-434
- §3.3 — insert — the governing employer is the *window's* employer (posture, ordinance, group limit), also for amend and media-line create — bp_elections.py:83/121/220-221, bp_orders.py:199-200
- §3.3 — insert — funded amendment bumps `Employer.version` unconditionally, including a zero delta / unchanged committed total — bp_elections.py:288-289
- §3.3 — insert — reverse-funding `reason` has no length bound (empty string accepted) — bp_elections.py:316
- §3.3 — insert — reverse-funding bumps `Employer.version` unconditionally and does **not** zero the allocation figures or touch media/`fulfillment_status` — bp_elections.py:326-338
- §3.5 — insert — OrderBatch list filters: `election_window_id`, `status`, `region_code` (previously undocumented) — bp_orders.py:103-105
- §3.6 — insert — `tracking_ref` required, ≥1 char, not blank, stored verbatim — bp_orders.py:349-350
- §3.7 — insert — claim submission is ungated by the swipe's posture, any number of claims per swipe, transaction not bumped — bp_cards.py:185-197
- §3.7 — insert — approve/reject answer with the claim row; deny-substantiation/reopen answer with the transaction — bp_cards.py:252/276 vs 140/172
- §3.7 — insert — deny `reason` required, ≥1 char, non-blank, never persisted — bp_cards.py:134-135
- §3.7 — insert — reopen `reason` same rule — bp_cards.py:147-148
- §3.9 — insert — payroll file `(employer_id, period_month)` not unique; `program_status` consulted by no payroll operation — bp_payroll.py:36-52, 86, 113, 130

Notes for the caller: per instruction I patched documentation only — bp_orders.py's unguarded replacement-fee debit was left as-is and the PRD now describes it. Two of my edits land in §3.8 (Pass B's section) because my file's unguarded fee is what falsifies its "balance can never be negative" claim; I found no Pass A or Pass B edit that I believe is wrong.

### Orchestrator verification of Step 9

- `PRD_COMPLETED.md` is 459 lines / 126,348 bytes and is NOT byte-identical to its source `PRD_FINALIZED.md` (107,807 bytes) — so the scan really ran; total growth across the three passes is +18,541 bytes / +17.2%.
- The file still ends at a real section boundary (final row of the §5 error-code table, `ERR_CLAIM_AMOUNT_MISMATCH | 422`) and retains all 29 headings — no truncation, no new sections.
- 55 edits total (43 ambiguity-pins, 12 mismatch-revisions): Pass A 15, Pass B 19, Pass C 21.
- No file under `workspace/implementation/` has an mtime later than 03:46, i.e. all of them predate the green 04:01 sweep. Steps 8 and 9 were documentation-only, so the 8×164/164 sweep results on disk still describe the current implementation exactly. No re-run was needed.
- Test suite integrity re-checked at the end: 156 `Design:` tags, zero `pytest.mark.skip`/`xfail`.

## Pipeline complete — 2026-09-04T04:36:00.000Z

All nine steps finished. Final green evidence: `workspace/implementation/results.{1..8}.json`, each `164 passed / 164 total`.
