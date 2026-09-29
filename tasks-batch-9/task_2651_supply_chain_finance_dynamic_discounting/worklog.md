# Worklog — task_2651_supply_chain_finance_dynamic_discounting

## Step 1: Create task directory — 2026-09-04T01:22:41.726Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2651_supply_chain_finance_dynamic_discounting` and `workspace/` (index pre-assigned by orchestrator prompt; no index auto-allocation performed).

## Step 2: Generate scaffold (prd-bench-scaffold-generator subagent) — 2026-09-04T03:13:00.000Z

(Note: the subagent appended its own short in-progress note here; replaced with its verbatim final summary below.)

All three scaffold artifacts are complete and lint-clean.

**Files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2651_supply_chain_finance_dynamic_discounting/`)
- `SCAFFOLD.yaml` — 2679 lines (151 KB)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 2656 lines (169 KB), single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4224 lines (256 KB), single top-level key `scaffold_corner_design`

`SCAFFOLD.yaml` contains neither design key (verified by parsing its top-level keys).

**SCAFFOLD.yaml counts (§1.0–§1.7)**: 14 entities, 47 endpoints, 11 state machines, 15 calculation rules, 28 validation rules (+3 validation_priority_pairs), 36 errors, 5 roles, 2 conserved-quantity invariants, 2 concurrency rules. Profile: `entity_topology: flat`, `state_machine_shape: parallel`, `consistency_model: immediate`, layers = dual_variant_calculation / selector_policy / optimistic_concurrency / cascading_side_effects / rate_threshold_triggers, `api_prefix: ""`.

**§1.8 index**: 9 difficulty rules × 22 instances (every rule ≥ 2).

**§1.9 index**: 9 sections, 72 instances = 52 real + 20 `excluded_because` stubs — entities 12, state_machines 13, calculations 15, validations 11, endpoints 6, errors 2, rbac 5, complexity_layers 7, consistency_model 1. Every stub's `difficulty_instance` was normalized to the SKILL.md `<rule_id> / <instance_name>` form and machine-verified to resolve to a real §1.8 instance; no `name` collides across the two design files; no stub carries a `test_recipe`.

**Error coverage**: all 36 error ids in the catalog are triggered somewhere across §1.8/§1.9 (the last three closed this session were `ERR_STALE_INVOICE_VERSION`, `ERR_STALE_OFFER_VERSION` via the two OCC instances and `ERR_FORBIDDEN_RESOURCE_SCOPE` via the cross-buyer/cross-supplier scope instance).

**Lint verdict (verbatim)**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           .../SCAFFOLD.yaml
  Difficulty design:  .../SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      .../SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    47
  §1.1 entities declared:     14
  §1.8 instances scanned:     22
  §1.9 instances scanned:     52
  Calls scanned (§1.8+§1.9):  1057

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Two fixes worth flagging from the final pass: (1) `POST /early-payments` bumps `DiscountOffer.version`, so the OCC instance's assert was corrected to `version == v_accepted + 1` rather than unchanged; (2) validation priority 5's `check` text in `SCAFFOLD.yaml` was pinned to evaluate resource scope only after the addressed id resolves, removing a 403-vs-404 ambiguity the new §1.9 FK/path-param instances assert against. No sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-09-04T03:12:45.323Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD (prd-bench-doc-generator subagent) — 2026-09-04T03:28:30.000Z

Orchestrator truncation check: PRD.md = 425 lines / 110,685 bytes, 28 headings, ends at a real section boundary (final row of the §5 error catalogue table, `| \`ERR_BUYER_CREDIT_LIMIT_EXCEEDED\` | 402 |`). NOT truncated — no regeneration needed.

Subagent summary (verbatim):

PRD.md is complete and verified.

**Output:** `.../workspace/PRD.md` — **425 lines**, ending at a real section boundary (final §5 table row `| \`ERR_BUYER_CREDIT_LIMIT_EXCEEDED\` | 402 |`), not mid-sentence.

**Top-level sections**
1. `## 1. Introduction`
2. `## 2. Global Specifications & System-Wide Principles` — 2.1 Participants/Identity/RBAC, 2.2 API Response Structure (verbatim contract block, byte-identical), 2.3 Pagination/Filtering/List Ordering, 2.4 Resource Identity/Timestamps/Logical Clock, 2.5 Money/Rates/Rounding, 2.6 Stale-Version Guards, 2.7 Rejection Precedence, 2.8 Segregation of Duties, 2.9 Nested Reads & Reverse Lookups, 2.10 Cascade Discipline & Conserved Quantities
3. `## 3. Business Logic & Workflows` — 3.1 Buyer onboarding & programme config, 3.2 Supplier onboarding (two verification axes), 3.3 Approved payable ingestion & invoice pricing, 3.4 Disputes/suppression/release, 3.5 Auction windows & session clearing, 3.6 Naming/countering/accepting a rate, 3.7 Funder capital, tranches & funder selection, 3.8 Reserve/execute/settle early payment, 3.9 Accounting treatment & reclassification, 3.10 Adoption, rate optimisation & concentration reporting
4. `## 4. Endpoint Definitions` (47-row table: Method | Path | Description | Authorized Role(s))
5. `## 5. Error Code Catalogue` (36-row table: Error ID | HTTP Status Code)

**Hard Contract reports (transcript only — not written into PRD.md or any sibling file)**
- **Contract 1 — Field-Name Coverage: PASS.** 110/110 entity field names, 64/64 endpoint input field names, 18/18 additional identifiers, all enum values, all state names, all 36 error ids, all 5 role names, all rejection reasons — 0 missing, each in backticks.
- **Contract 2 — Rule Coverage: PASS.** 62/62 transitions across all 11 machines; 15/15 calculations with every variant pair (`days_early`, `early_payment_discount`, `supplier_concentration`) and pinned evaluation/rounding order (per-line tax then sum; fee tier keyed on pre-fee net; round_half_up; 360-day basis); 28/28 validations with priority position, `applies_to`, error id and HTTP status, plus all 3 `validation_priority_pairs` outcomes; 2/2 concurrency rules; 2/2 invariants with forward and compensating actions; all global constants and list conventions.
- **Contract 3 — §3 Path Purity: PASS.** 1027 backtick tokens in §3 scanned: 0 `/`-prefixed tokens, 0 bare HTTP methods, 0 method+path combos, 0 plain-text path leaks.

**Independent table cross-check:** §4 rows == scaffold endpoints exactly (47/47, method+path matched pairwise); §5 rows == scaffold errors exactly (36/36, order preserved, 0 HTTP-status mismatches).

**Scaffold self-inconsistencies resolved (choice documented in prose):**
- `Dispute.reason_code`: used the §1.1 field table's `SHORT_SHIPMENT`; the endpoint description's contradictory `QUANTITY_SHORT` appears nowhere in PRD.md.
- `computed_total_cents`: accepted-rows-only semantics (validation 18 + state-machine preconditions, 2 of 3 sources) over the entity description's "all rows".
- `POST /funders/{id}/pause`: endpoint `roles: [PlatformOps, Funder]` treated as authoritative over the state machine's narrower `actor: PlatformOps`.
- APR floor: entity constraint (`1..max_acceptable_apr_bps`) reconciled with validation 19 (`[200, max_acceptable_apr_bps]`) — §2.7 item 19 and §3.6 both state the 200 bps floor, the programme ceiling, and the `FIXED_RATE` exact-match requirement, all under `ERR_APR_OUT_OF_PROGRAM_BOUNDS`.

Also fixed three stale §-cross-references. Neither design yaml was opened, grepped, or referenced, and no sibling task directory was read. Note: §3 has 10 subsections rather than the skill's suggested 5–9 — a deliberate call to keep coverage lossless across 14 entities.

## Step 5: Generate unit tests (prd-bench-unit-test-generator subagent) — 2026-09-04T04:38:00.000Z

Test infrastructure and suite are complete at the task root.

## Files written

`TASK_ROOT = /home/ubuntu/github/CodingPRD/tasks/task_2651_supply_chain_finance_dynamic_discounting`

**`test_helpers/`** (2,229 lines): `__init__.py` 1, `api_client.py` 395, `api_errors.py` 137, `assertions.py` 325, `constants.py` 96, `factories.py` 362, `fixtures.py` 625, `test_users.py` 70, `types.py` 218.

**`test_suite/`** (11,400 lines): `conftest.py` 29; queue A `test_01` 512/4, `test_02` 556/6, `test_03` 829/6, `test_04` 627/4, `test_05` 731/6, `test_06` 523/4, `test_07` 862/6, `test_08` 602/4, `test_09` 861/4; queue B `test_10` 898/11, `test_11` 1073/12, `test_12` 898/7, `test_13` 372/5, `test_14` 754/6, `test_15` 222/2, `test_16` 512/5, `test_17` 355/3, `test_18` 184/1.

**96 tests total** (44 queue A, 52 queue B). Nothing was written under `workspace/`; `workspace/implementation/` was never read or touched; no sibling task directory was read.

## Coverage

- **Queue A (§1.8):** 22 of 22 instances translated, every one with >=2 tests. Zero skips.
- **Queue B (§1.9):** 72 instances — all 52 non-stub instances translated with >=1 test; the 20 `excluded_because:` stubs were correctly not translated (each cross-references a queue-A instance that owns the assertion).

## Verification performed myself (not trusted from subagent reports)

- `python3 -m py_compile` on all 27 `.py` files: clean; `__pycache__` removed.
- AST scan: exactly one `Design:` line per test, always the last docstring line, format `Difficulty/<rule_id>/<name>` or `Corner/<section>/<name>`, and every tag resolves to a real instance name in the source yaml. No untagged, dual-tagged, or dangling tags.
- 263 PRD citation fragments machine-checked as whitespace-normalised verbatim substrings of `workspace/PRD.md`: **0 non-verbatim**.
- AST scan for the two framework-signature hazards: no `validate_error(resp, <int>)` and no `validate_success(...)["data"]` double-unwrap anywhere. No `body["error"]["error_id"]` paths.
- No `skip` / `skipif` / `xfail` / `TODO` / placeholder anywhere.

## Fixes made during this final pass

- **`test_07_cross_entity_state_dependency.py` written** (862 lines, 6 tests) for the three cross-entity instances: paused-funder waterfall reporting `ERR_NO_ELIGIBLE_FUNDER` (422) rather than the first candidate's 402 then succeeding on `FUNDER` at net 988034 / funder available 59011966; the session lifecycle gating one byte-identical naming body across `SCHEDULED`->`LIVE` (inclusive `opens_at`) and the SETTLE-close split where `counter` reports `ERR_SESSION_NOT_LIVE` (rule 9) while `accept` reports `ERR_ALREADY_TERMINAL` (rule 10); and the mid-flight sanctions hold freezing `execute` with 403 while the `RESERVED` encumbrance of 98756 and zero advices persist, then executing cleanly with advice `RA-<invoice_number>-01`, value date 2026-08-07, `SENT`.
- **Added a second test to `test_03`** — the skill's "every difficulty instance has at least TWO tests" was short by one on `offer_counter_rename_cycle_bounded_at_three_rounds`.
- **Removed two skill violations of "code must never mention scaffold"**: `test_10`'s module docstring named `SCAFFOLD_CORNER_DESIGN.yaml`, and `test_07` had three "Instance N scaffolding" section comments. Both reworded.
- Removed one unused import (`test_01`) and one unused constant (`test_09`).

## Places where the PRD was followed over the design yaml

1. Design gives supplier T `bank_status PENDING` after onboarding submit; PRD §3.2 says `NOT_STARTED` — used `NOT_STARTED`.
2. Design's FIXED_RATE "Empty Programme" omits `fixed_apr_bps`; PRD §3.1 makes it mandatory — added `fixed_apr_bps: 1000`.
3. Design uses `reason_code: QUALITY_REJECTION`, absent from PRD §3.4's enum — used `GOODS_REJECTED`.
4. Design captures a funder `committed_capital` field the PRD never defines — asserted on `available_capital_cents` plus `assert_funder_capital_conserved`.
5. Absolute `version` numbers the PRD does not pin are asserted as `+1` deltas rather than literals.
6. The non-rising counter/rename APR rejection carries no PRD-pinned error id, so no error id is asserted for it anywhere; a hold round trip's preservation of the original `payment_ready_at` value is likewise not derivable, so only `is not None` is asserted.

## Step 6: Generate implementation (prd-bench-implementation-generator subagent) — 2026-09-04T04:02:00.000Z

Implementation complete and verified.

## Files written (24 files, 3341 lines)

`.../workspace/implementation/` — `start.sh` 10 (executable), `requirements.txt` 1, `app.py` 79, `db.py` 144, `errors.py` 92, `response.py` 50, `middleware.py` 185, `validation.py` 210, `services/calc.py` 204, `services/recompute.py` 268, `services/flows.py` 264, `services/guards.py` 151, `routes/payments.py` 338, `routes/offers.py` 248, `routes/suppliers.py` 218, `routes/programs.py` 209, `routes/files.py` 195, `routes/invoices.py` 171, `routes/funders.py` 138, `routes/sessions.py` 78, `routes/buyers.py` 69, `routes/clock.py` 19, `routes/__init__.py` + `services/__init__.py` 0.

## Coverage
**47/47 endpoints** registered (enumerated and counted from the blueprints — matches the PRD §4 table exactly). All 14 entities, 11 state machines (incl. parallel axes on EarlyPayment, the Supplier fork-join, and the cyclic programme/offer/funder/bank edges), 15 calculations (Decimal + ROUND_HALF_UP throughout, 360-day basis), the 28-step rejection-precedence ladder, all 36 error ids with their HTTP codes, 5 roles with ownership scoping, both conserved quantities (full recomputation, never delta-adjusted), and both OCC guards (`expected_invoice_version`, `expected_offer_version` — mandatory, omission -> `ERR_INVALID_REQUEST`).

## Verification
- `python3 -m py_compile` — **22/22 .py files OK**
- Audits: no sqlite / file I/O / `/tmp` / pickle / `seed_*`; no `float` or builtin `round()` in any arithmetic.
- **Cold boot: responded in ~1.5 s** on `PORT=18653` bound to `0.0.0.0`, store confirmed empty, clock defaults to `2026-08-01T00:00:00Z`. Killed by specific pid only; no broad `pkill`.

Two smoke scripts (~60 calls) passed end to end and reproduce the PRD's pinned worked examples exactly: line taxes 2917/2917/2917 -> face **108751**; micro-deposit code **789987**; funder reservation `days_early 56 / discount 1353 / fee 677 / net 106721`; value-date settlement `days_early 54 / discount 1305 / true_up -48`; advice `RA-INV-1-01`; analytics ceiling tightened 1200 -> **600** under `THROTTLED`. The edge pass confirmed: partial file ingest (3 accepted / 3 rejected in narrative reason order, totals reconciled against accepted rows only), 422 on control-total mismatch with nothing persisted, auto `BUYER_FILE_SUPPRESSION` dispute, pagination bounds (limit 0 and 101 -> 400), session 60-minute cooldown, stale/missing OCC (412 / 400), `BUYER_SELF` waterfall, the dispute cascade (offer -> `VOIDED_BY_SUPPRESSION`, payment -> `VOID`, credit released to 0), the `SUPPRESSED -> ELIGIBLE` revert on withdrawal, and the clock sweep maturing only the due non-suppressed invoice.

One PRD subtlety worth flagging as intentional: §2.10 means a wrong micro-deposit code bumps the bank account's `version` but leaves the supplier untouched — confirmed in the smoke run.

## Step 7: Run tests and iterate (long-lived fix subagent) — 2026-09-04T04:50:00.000Z

Orchestrator independent verification of the final sweep artifacts (per the known "subagent claims a clean sweep with no results files" failure mode): all 8 of `workspace/implementation/results.{1..8}.json` exist, ~28.8 KB each, mtime 04:48, and each reports `passed: 96, failed: 0, total: 96, errors: 0, skipped: 0`. Confirmed clean.

Subagent summary (verbatim):

Clean 8-round sweep achieved. Layout is correct, no stray artifacts.

## Summary

**Iterations run:** 2

- Iteration 1: 93/96 in all 8 rounds — the same 3 tests failed in 8/8 rounds (fully deterministic, zero flakiness; no timeouts or connection errors, so no load-induced noise to rule out).
- Iteration 2: **96/96 in all 8 rounds.**

**Tests deleted:** none. All three failures passed STEP 1 (PRD verbatim-covers the rule and uniquely determines the outcome), so they were resolved at STEP 2 as test-side mis-translations.

**Fixes applied to `test_helpers/`:** none — the fixtures, factories and role-header builders were all PRD-faithful.

**Fixes applied to `implementation/`:** none. The implementation was correct on all three points; each failure was the test asserting something the PRD contradicts.

**Fixes applied to `test_suite/`** (all STEP 2, assertion mis-translation — made strictly more faithful to PRD, no assertion weakened, no `error_id` downgraded, no skip/xfail added):

1. `test_05_priority_pair_validation_conflict.py::test_an_acceptance_deadline_exactly_equal_to_the_clock_is_already_closed` — asserted a never-accepted offer carries `accepted_apr_bps=None`. PRD §3.6 states verbatim that an offer "opens in `status` `NAMED` with `counter_round` 0, `counter_apr_bps` null, `accepted_apr_bps` 0 and `accepted_at` null" — the same sentence deliberately contrasts `0` for this field against `null` for the two neighbours. Changed to `accepted_apr_bps=0`.

2. `test_06_boundary_precision_check.py::test_projected_concentration_share_five_cents_past_the_cap_is_refused` — two sites. The offer assertion had the same `None`-vs-`0` error as above; the invoice assertion had it too, against PRD §3.3: an invoice "opens with `face_covered_cents` at 0 ... with `accepted_apr_bps`, `provisional_discount_cents`, `final_discount_cents` and `discount_true_up_cents` all at 0". Both changed to `accepted_apr_bps=0`.

3. `test_11_corner_state_machines.py::test_cancelling_a_session_that_holds_an_accepted_offer_returns_invalid_state` — asserted the absolute `session["version"] == 2`, reasoning "1 at creation plus 1 for the clock-driven SCHEDULED -> LIVE move". That arithmetic omits a third mutation the PRD requires: naming the offer moves the session's persisted `named_offer_count` from 0 to 1 (§3.5: "Either way the session's `named_offer_count` reflects the new offer"), and §2.4 pins `version` to increase "by exactly 1 on every mutation of that row" while §2.10 extends that to rows "the caller did not address". Correct value is therefore 3. Replaced the brittle absolute literal with a read of the session's version immediately before the rejected CANCEL and an equality check against it — this preserves the test's actual intent ("the rejected call adds none") and still catches any spurious mutation on the rejection path.

**Notable implementation behaviour confirmed correct (not changed):** `services/flows.py::refresh_named_offer_count` bumps the session's `version` only when the count actually changes, so acceptance does not bump it a second time — matching §3.5's "Because `ACCEPTED` is already inside that set, acceptance does not increment the counter a second time" together with §2.10's rule that a row a cascade merely re-reads without changing does not have its `version` touched.

### Orchestrator note on Step 8 skip condition

Step 7 reported 0 deletions, 0 `test_helpers/` fixes and 0 `implementation/` fixes, but 3 `test_suite/` fixes (4 assertion sites) across 2 iterations — i.e. NOT a zero-iteration baseline exit. The skill's skip condition requires all four counters at zero, so Step 8 runs. The three `test_suite/` fixes are the PRD-ambiguity signal to target: they mark places where the PRD's `null`-vs-`0` initial-value contract and its version-bump cascade semantics were readable two ways by the test generator, which is exactly the class of silence Step 8 exists to pin.

## Step 8: Finalize PRD (PRD finalizer subagent) — 2026-09-04T05:03:30.000Z

Orchestrator verification: `PRD.md` 425 lines / `PRD_FINALIZED.md` 425 lines; `diff` shows exactly one changed line (237, the §3.5 `named_offer_count` paragraph); file still ends at the final §5 error-catalogue row — not truncated.

Subagent summary (verbatim):

Done. One edit, one line.

## Line counts
- `PRD.md`: 425 lines; `PRD_FINALIZED.md`: 425 lines. Exactly 1 line changed (§3.5, line 237) → **0.24 % of lines**, +0 lines. File verified intact: still ends at the last row of the §5 error-catalogue table (`ERR_BUYER_CREDIT_LIMIT_EXCEEDED | 402`).

## Changes
- **§3.5 (`named_offer_count` paragraph) — revise** — pinned that `named_offer_count` is a *stored* figure (not derived at read time), re-derived by recounting the session's `NAMED`/`COUNTERED`/`ACCEPTED` offers at the end of every operation that creates or re-statuses an offer on it (naming incl. the supersede self-edge, counter, re-name, accept, session-close, session-cancel, programme-close, dispute-suppression); that a recount which leaves the figure unchanged is not a session mutation and does not touch `version`, while a changing one is — so naming the first offer moves 0 -> 1 and bumps the session's `version`, whereas counter/re-name/accept do not; and that the step-four invoice-maturity sweep is the single exception, expiring an invoice's outstanding offers without recounting, so the stored figure can keep counting an expired offer until the next recount — `services/flows.py:30-38`, `routes/offers.py:31-33`, `services/flows.py:113-119`.

**No edit for Step 7 items 1 and 2** (`accepted_apr_bps` asserted as `None`): impl creates offers with `accepted_apr_bps: 0` (`routes/offers.py:94`) and invoices with `accepted_apr_bps/provisional_discount_cents/final_discount_cents/discount_true_up_cents` all `0` (`routes/files.py:162-169`), which is exactly what PRD §3.6 and §3.3 already state verbatim. I also checked §4/§5 for a contradicting field schema — the endpoint sections carry no per-field nullability tables, so there is no internal PRD ambiguity to pin. Pure test-side bugs. Concentration-gate rounding (the other half of item 2) also already matches: `recompute.projected_concentration_pct` rounds half-up to two decimals and `guards.py:143` refuses only on strictly greater than the cap, as PRD §3.6/§2.7-25 say.

## Pre-edit search log (edit 1)
- **(a) Subject:** the session's stored `named_offer_count` and the session `version` increments its recomputation causes.
- **(b) Paths enumerated:** grep across `implementation/` for `named_offer_count`, `refresh_named_offer_count`, `expire_offers`, `mature_invoice`, `close_session`, `cancel_session`, plus a grep of *every* offer `status` write. Read: `services/flows.py` (`refresh_named_offer_count` L30-38, `close_session` L53-59, `cancel_session` L62-66, `suppress_invoice` L73-83, `mature_invoice` L113-119, `run_clock_sweep` steps 2-4 L126-172), `routes/offers.py` (`_refresh_session` L31-33 and its four callsites: create L104-108, counter L175, rename L208, accept L245; offer creation L84-96), `routes/sessions.py` (creation with `named_offer_count` 0 L43-55; close endpoint L58-78), `routes/programs.py` (`_close_cascade` L127-147), `routes/invoices.py` (raise-dispute -> `suppress_invoice`; UPHELD resolution inlines `MATURED` and expires nothing because the offers were already voided at raise time), `routes/payments.py` (confirmed reservation/execution/settlement never write an offer's `status`, so no recount is owed there), `db.py` (`touch`, `public` — sessions are serialised straight from the row, no read-time recompute).
- **(c) Wording adjustments made:** (i) deliberately did **not** assert a total `version` delta for the close/cancel cascades — `flows.close_session`/`cancel_session` recount *before* a single `touch`, giving one combined bump, while the clock-driven close (sweep step 2 then step 3) and `_close_cascade` bump once on the status change and again on a changing recount; the committed sentence only says a changing recount "is such a mutation", leaving those totals as under-determined as PRD.md already leaves them; (ii) narrowed the concrete example to "naming the **first** offer on a session", because the supersede self-edge removes one counted offer and adds another, leaving the figure — and hence the session's `version` — untouched; (iii) added the maturity-sweep exception clause after confirming `mature_invoice` is the only offer-expiring path with no session recount.

## Step 9: Complete PRD (completeness scan, 3 sequential file-partitioned passes) — 2026-09-04T05:36:00.000Z

Orchestrator design decision: Step 9 was run as THREE sequential file-partitioned subagent passes over one shared `PRD_COMPLETED.md` rather than one monolithic scan. A single agent asked to walk 24 implementation files / 47 endpoints against a 111 KB PRD reliably returns a byte-identical no-op; partitioning by implementation file forces each pass to actually read its slice. Passes were sequential (not concurrent) because all three edit the same output file.

- Pass A partition: `app.py`, `db.py`, `errors.py`, `response.py`, `middleware.py`, `validation.py`, `start.sh`, `requirements.txt` → created `PRD_COMPLETED.md` from `PRD_FINALIZED.md`, edited §2.1–§2.7 + §4 intro.
- Pass B partition: `services/calc.py`, `recompute.py`, `flows.py`, `guards.py` → edited §2.7, §3.4, §3.5, §3.10.
- Pass C partition: all 11 `routes/*.py` → edited §2.1, §2.5, §2.7, §3.1–§3.10.

Orchestrator verification of the final artifact: `PRD_COMPLETED.md` = 426 lines / 135,655 chars vs `PRD_FINALIZED.md` 425 lines / 111,807 chars (**+23,848 chars**, +1 line). `cmp` confirms it is NOT byte-identical to `PRD_FINALIZED.md`, so the scan genuinely ran. All 5 `## ` sections present; §4 endpoint table 47 rows; §5 error catalogue 36 rows; file ends at `| \`ERR_BUYER_CREDIT_LIMIT_EXCEEDED\` | 402 |` — not truncated.

Aggregate across the three passes: **40 ambiguity-pins, 24 mismatch-revisions (64 changes)**, all in-paragraph inserts/revisions — no new sections, no lines removed.

### Pass A summary (verbatim)

- `PRD_FINALIZED.md`: 425 lines / 111,807 chars; `PRD_COMPLETED.md`: 426 lines / 118,102 chars (+1 line, +6,295 chars). 13 diff hunks, all confined to §2.1–§2.7 and the §4 intro. §3 and §5 untouched. Not truncated. Cross-checked all 36 error ids and HTTP statuses in `errors.py::ERROR_STATUS` against the §5 catalogue programmatically: exact match, no edit needed.
- Counts: ambiguity-pins 10, mismatch-revisions 4.
- §2.1 — revise — ambiguity — both auth headers are trimmed before use (whitespace-only counts as empty), the trimmed `X-User-ID` is what ownership checks compare, role matching is case-sensitive — `middleware.py:46-49`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly twenty upper-case-alphanumeric characters — `response.py:10,14`
- §2.2 — revise — mismatch — `api_request_timestamp` is stamped from real wall-clock time, not the logical clock — `response.py:18` → `db.py:63`
- §2.2 — revise — mismatch — error envelope covers 4xx and 5xx, not 4xx only — `app.py:67-69`
- §2.2 — insert — ambiguity — unrouted paths → `ERR_INVALID_REQUEST` at 404, unsupported method → 405, both decided by routing before the §2.7 check-1 authentication gate — `app.py:54-65`
- §2.3 — revise — ambiguity — `limit`/`offset` present-but-blank/non-integer is rejected rather than defaulting; only absence defaults; `offset` has no upper bound — `validation.py:176-196`, `response.py:39`
- §2.3 — revise — ambiguity — `created_at` ties are broken by a monotonic server-wide creation sequence — `db.py:132-134`
- §2.3 — revise — ambiguity — filter values are never validated against enums/id formats, are trimmed, and an empty filter is treated as absent — `validation.py:203-210`
- §2.4 — revise — ambiguity — `updated_at` equals `created_at` exactly at creation — `db.py:108-113`
- §2.4 — revise — mismatch — `created_at`/`updated_at` are carved out of the logical-clock rule and stamped from real wall time; client-supplied instants are echoed back character-for-character — `db.py:105-119,122-129,50-56`
- §2.5 — revise — ambiguity — `concentration_cap_pct` accepts a JSON number or numeric string, is quantised to 2 dp using half-to-even (the sole exception to §2.5's half-up rule), bounds checked post-quantisation — `validation.py:134-151`
- §2.7 check 3 — revise — ambiguity — six sub-rules: explicit `null` == omitted; absent-or-blank body == `{}`; non-object JSON body rejected wholesale; `Content-Type` never consulted; undeclared fields ignored; strict typing; string lengths measured untrimmed; timestamp parsing rules — `validation.py:25-32,35-49,62-91`, `db.py:67-82`
- §2.7 check 5 — revise — mismatch — `EarlyPayment`/`Dispute` carry no `supplier_id`, so Supplier scope resolves through the invoice; a `Funder` addressing a self-funded payment is always denied `ERR_FORBIDDEN_RESOURCE_SCOPE` — `middleware.py:156-185`
- §4 intro — revise — ambiguity — trailing slash is not significant and neither form redirects — `app.py:29`

### Pass B summary (verbatim)

- 426 lines (unchanged), 121,175 chars vs 118,102 at start (+3,073). Not truncated; pass A's edits verified intact.
- Counts: 5 ambiguity-pins, 3 mismatch-revisions.
- §2.7 check 7 — revise — mismatch — the check is the invoice's `dispute_suppressed` flag alone; an upheld resolution leaves the flag set on a `MATURED` invoice, which still reports `ERR_INVOICE_DISPUTE_SUPPRESSED` — `services/guards.py:23-25`
- §2.7 check 28 — insert — ambiguity — `credit_used_cents` is re-derived at check time, excluding the payment being re-priced on the execute path — `guards.py:148-151`, `recompute.py:169-182`
- §3.4 hop four — insert — ambiguity — hop four is a second write to the invoice row, so an invoice carrying a reserved/deployed payment advances `version` by two — `flows.py:106`, `recompute.py:198-212`
- §3.5 sweep step three — insert — ambiguity — the post-expiry recount is a second write, so a clock-closed session with outstanding offers advances `version` by two — `flows.py:152-161`
- §3.5 sweep step four — revise — ambiguity — maturity comparison is date-vs-date and strictly greater, so an invoice does not mature on its due date — `flows.py:163-169`
- §3.5 sweep step five — revise — mismatch — tranche expiry is likewise strict; every funder is recomputed against the new clock date, unchanged funders left unwritten — `flows.py:174-183`, `recompute.py:139-157`
- §3.5 early close — insert — mismatch — `SETTLE`/`CANCEL` write the session row exactly once even when the recount changed — `flows.py:53-66`
- §3.10 — insert — ambiguity — `adoption_rate_pct` two-decimal quantisation is internal; the wire form is a JSON number, so zero reads back as `0.0` — `recompute.py:113-114`
- Deliberately not changed (impl already uniquely pinned): every calc formula and rounding order, funder score/tie-break chain, waterfall exhaustion error precedence, all guard error ids and boundary strictness in checks 9/16/19/20/25, and the conserved-quantity full recomputations.

### Pass C summary (verbatim)

- 426 lines (unchanged), 135,655 bytes vs 121,175 at start = +14,480 chars. 43 targeted Edit calls, 42 distinct changes. No Write, no section added, no line added or removed.
- Counts: 25 ambiguity-pins, 17 mismatch-revisions.
- Handed-over decision resolved: the three percentages emit as Python floats. Pinned in §2.5 as a general outbound rule — every percentage the API exposes is a plain JSON number, not a two-decimal string (`60.00` reads back as `60.0`, `33.33` as `33.33`) — and echoed at §3.10.
- §2.1 — insert — ambiguity — accept's status-dependent role narrowing runs after the offer resolves but before the scope test — routes/offers.py:213-218
- §2.5 — insert — ambiguity — all percentages serialise as JSON numbers; trailing zeros not preserved — routes/programs.py:54,173-175
- §2.7 check 3 — revise — mismatch — "start strictly before end" carved out for capital tranches (date-vs-date, equality accepted) — routes/funders.py:92
- §2.7 check 6 — insert — mismatch — `POST /discount-offers` resolves both body FKs before check 5 — routes/offers.py:51-53
- §2.7 check 22 — insert — mismatch — on micro-deposit confirm, checks 14 and 22 precede the terminal check 10 — routes/suppliers.py:192-197
- §3.1 — revise — ambiguity — `fixed_apr_bps` conditional presence/absence is `ERR_INVALID_REQUEST` at check 3, before the `buyer_id` lookup — routes/programs.py:37-40
- §3.1 — revise — mismatch — `CLOSE` accepts `DRAFT` as well as `OPEN`/`PAUSED` — routes/programs.py:119
- §3.1 — insert — mismatch — close cascade writes a cancelled session twice when it carried outstanding offers, and cancels sessions holding `ACCEPTED` offers — routes/programs.py:135-147
- §3.2 — revise — ambiguity — `remittance_email` is 1–320 characters — routes/suppliers.py:31
- §3.2 — revise — mismatch — `identity_score` is written on any of the three decisions whenever supplied, left untouched when omitted — routes/suppliers.py:79,86-87
- §3.2 — revise — mismatch — IDV-`FAILED` cascade sets `bank_status` unconditionally and fails every account not already `REPLACED`/`FAILED`, in `created_at` order — routes/suppliers.py:100-105
- §3.2 — insert — ambiguity — bank-account registration has no `onboarding_status` precondition and always writes the supplier row — routes/suppliers.py:134-155
- §3.2 — revise — ambiguity — `code` is 1–32 characters; all three outcomes answer 200 with the bank-account row — routes/suppliers.py:189
- §3.2 — insert — ambiguity — applying a hold leaves `payment_ready_at` as it stood — routes/suppliers.py:118-121
- §3.2 — insert — ambiguity — release stamps `payment_ready_at` only when null, never overwrites, never restores `DRAFT` — routes/suppliers.py:126-127
- §3.3 — insert — ambiguity — `rows` may be empty; refusal comes from control-total reconciliation, not shape — routes/files.py:95
- §3.3 — insert — ambiguity — row-reason precedence pinned: `SUPPLIER_UNKNOWN` → `DUPLICATE_INVOICE_NUMBER` → `NON_POSITIVE_AMOUNT` → `DUE_DATE_NOT_AFTER_APPROVAL` → `EMPTY_LINES` — routes/files.py:71-84
- §3.3 — insert — ambiguity — within-file duplicates resolve in submitted order; a rejected row claims nothing — routes/files.py:121
- §3.3 — revise — mismatch — duplicate/non-contiguous `line_no` is `ERR_INVALID_REQUEST` for the whole file; lines are re-ordered to ascending `line_no` — routes/files.py:52-58
- §3.4 — revise — mismatch — `resolution_note` (1–2000) is stored as given even while the dispute is `OPEN` — routes/invoices.py:100,113
- §3.4 — revise — mismatch — inbound `reason_code` admits only the three client codes; over-face `disputed_amount_cents` → `ERR_INVALID_REQUEST` after scope but before the state checks — routes/invoices.py:95-101
- §3.4 — insert — ambiguity — raise-dispute state conditions report `ERR_INVALID_STATE`, never `ERR_INVOICE_DISPUTE_SUPPRESSED` — routes/invoices.py:103-106
- §3.4 — revise — mismatch — all three resolutions are open to both `BuyerAdmin` and `PlatformOps` — routes/invoices.py:131
- §3.4 — revise — mismatch — removed the "available to a platform operator" clause on `UPHELD` — routes/invoices.py:131
- §3.4 — revise — mismatch — the invoice `version` moves only when the invoice row is actually written — routes/invoices.py:147-167
- §3.5 — insert — ambiguity — session windows are never compared to the clock, so a wholly past window may be scheduled — routes/sessions.py:26-29
- §3.6 — insert — ambiguity — `session_id` is not cross-checked against the invoice's programme — routes/offers.py:41,54,60-61
- §3.6 — revise — ambiguity — pay-date-before-clock and deadline-after-clock are `ERR_INVALID_REQUEST` at check 3; "strictly before `net_due_date`" is enforced only via `ERR_INSUFFICIENT_DAYS_EARLY` — routes/offers.py:46-55,76
- §3.6 — insert — ambiguity — counter's `program_type` and strictly-greater rate conditions are `ERR_INVALID_STATE` — routes/offers.py:161-166
- §3.6 — insert — ambiguity — a revised `requested_pay_date` on rename is re-validated against nothing — routes/offers.py:184,205-206
- §3.6 — revise — ambiguity — the session-live condition at acceptance is `ERR_INVALID_STATE`, not `ERR_SESSION_NOT_LIVE` — routes/offers.py:224-226
- §3.7 — insert — ambiguity — tranche interval compared date-vs-date; tranche creation has no funder-status precondition — routes/funders.py:92,96-123
- §3.7 — insert — ambiguity — a tranche covering today bumps the funder `version`; one wholly future/past does not — routes/funders.py:122
- §3.7 — revise — mismatch — `WITHDRAW` advances `version` by two when available capital was non-zero; a `WITHDRAWN` funder reports `ERR_INVALID_STATE` — routes/funders.py:70-81
- §3.8 — insert — ambiguity — a non-`ACCEPTED` offer at reservation is `ERR_INVALID_STATE` — routes/payments.py:64-67
- §3.8 — revise — ambiguity — `override_reason` is also null at reservation — routes/payments.py:107
- §3.8 — revise — mismatch — value-date days early can go negative, yielding a negative discount, net above face and a negative true-up — routes/payments.py:258-259
- §3.8 — revise — mismatch/ambiguity — execute's suppressed-invoice condition is `ERR_INVALID_STATE`; execution re-runs the `min_days_early` floor; `execution_date`/`value_date` render as canonical midnight instants — routes/payments.py:190-215
- §3.8 — revise — mismatch — the invoice row is written unconditionally on execute — routes/payments.py:222-223
- §3.8 — insert — ambiguity — `failure_reason` is required (1–500) but validated and discarded — routes/payments.py:287
- §3.9 — insert — ambiguity — `override_reason` has no minimum length; omission leaves the prior value — routes/payments.py:322,331-332
- §3.10 — revise — ambiguity — analytics field order is fixed; counts/rate/posture/weighted average derived live, the ceiling rule is not run, no `version` moves — routes/programs.py:164-176
- Integrity: 426 lines, §4 table 47 rows, §5 table 36 rows, all 5 `## ` headings at original line numbers, passes A and B spot-checked intact.

## Pipeline complete — 2026-09-04T05:36:00.000Z

All 9 steps done. Final state: 96/96 tests passing in all 8 parallel rounds; `workspace/PRD_COMPLETED.md` written.
