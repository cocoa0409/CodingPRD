# Worklog — task_2659_carrier_interconnection_access_billing

## Step 1: Create task directory — 2026-09-04T02:18:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2659_carrier_interconnection_access_billing` and its `workspace/` subdirectory. Index 2659 was pre-assigned by the invoking orchestrator; no scan of `./tasks/` was performed and no other task directory was created.

## Step 2: Generate Scaffold — 2026-09-04T04:05:00.000Z

All three artifacts are final and on disk, and the lint gate passes.

Lint verdict (verbatim, `python3 skills/prd-bench-scaffold-generator/scaffold_lint.py /home/ubuntu/github/CodingPRD/tasks/task_2659_carrier_interconnection_access_billing`):

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           /home/ubuntu/github/CodingPRD/tasks/task_2659_carrier_interconnection_access_billing/SCAFFOLD.yaml
  Difficulty design:  /home/ubuntu/github/CodingPRD/tasks/task_2659_carrier_interconnection_access_billing/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      /home/ubuntu/github/CodingPRD/tasks/task_2659_carrier_interconnection_access_billing/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    80
  §1.1 entities declared:     14
  §1.8 instances scanned:     20
  §1.9 instances scanned:     77
  Calls scanned (§1.8+§1.9):  1343

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files: SCAFFOLD.yaml 198,718 bytes / 3,840 lines; SCAFFOLD_DIFFICULTY_DESIGN.yaml 134,322 bytes / 2,994 lines; SCAFFOLD_CORNER_DESIGN.yaml 373,222 bytes / 8,878 lines.

**SCAFFOLD.yaml (§1.0–§1.7)** — 14 entities, 13 state machines, 2 concurrency rules, 9 calculations, 74 validations, 80 endpoints (39 GET / 41 POST), 69 error ids, 8 roles. Top-level keys are exactly scenario, domain_name, api_prefix, response_envelope, complexity_profile, entities, state_machines, concurrency_rules, calculations, validations, endpoints, errors, roles — neither design key is present. Complexity profile: primary `multi_party_negotiation`, secondary `ledger_reconciliation`; layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `rate_threshold_triggers`, `ops_run_checkpoint`; graph topology, cyclic state machines, segregation-of-duties role model, immediate consistency.

**SCAFFOLD_DIFFICULTY_DESIGN.yaml (§1.8)** — single top-level key; all 9 §0.5 rules covered by 20 instances, each with a differentiation clause: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 3, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

**SCAFFOLD_CORNER_DESIGN.yaml (§1.9)** — single top-level key; all 9 taxonomy sections present, 93 instances (77 full `test_recipe`s + 16 `excluded_because` stubs): entities 13, state_machines 20, calculations 12, validations 8, endpoints 7, errors 20, rbac 6, cross_cutting_complexity_layers 6, consistency_model 1.

Verified this pass:
- Every one of the 69 error ids is referenced by the design files (uncovered 0).
- No `setup_api_calls`, `trigger:`, `setup:` or `assert:` list is empty anywhere.
- Every stub's `difficulty_instance` resolves to a real §1.8 instance name (missing: none).
- Forbidden concurrency vocabulary count is 0 across all three files.

No sibling task directory was read, listed, or grepped at any point.

## Step 3: Copy Shared Files — 2026-09-04T04:06:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_2659_carrier_interconnection_access_billing/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-04T04:25:00.000Z

PRD complete and verified.

**Output:** `workspace/PRD.md` — **513 lines, 114,164 bytes**. Built incrementally (1 Write + 3 heredoc appends for §1–§3, 2 generated appends for §4/§5, then targeted repair edits). Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened or grepped; no sibling task directory was read.

**Exact last 5 lines:**
```
| `ERR_INVOICE_NOT_ISSUED` | 409 |
| `ERR_EMPTY_INVOICE` | 409 |
| `ERR_PAYMENT_EXCEEDS_BALANCE` | 422 |
| `ERR_DISPUTE_AMOUNT_EXCEEDS_BALANCE` | 422 |
| `ERR_INVALID_CREDIT_AMOUNT` | 422 |
```
File ends at a real boundary — the final row of the §5 table. No audit footer, no contract report in the file.

**Sections:** §1 Introduction; §2 Global Specifications (2.1 RBAC → 2.11 Reserve Provisioning / append-only ledger, 11 subsections); §3 Business Logic (3.1 Carrier onboarding & negotiation cycle → 3.10 Record-exchange reconciliation, 10 subsections); §4 Endpoint Definitions; §5 Error Code Catalogue. `## `-level headings are exactly the five required.

**Coverage:** 14 entities and all 151 entity fields; 13 state machines and all 72 non-creation transitions (self-loops and multi-source groups included); 9 calculations with all 25 constants expressed numerically; 74 validations with the full 10-band priority ladder; 69 errors (every one referenced in §1–§3 narrative *and* listed in §5); 8 roles; 80 endpoints. §4 = 4 columns × 80 rows; §5 = 2 columns × 69 rows; §5 error IDs are a set-exact match to the scaffold.

**Hard contracts:**
- **Contract 1 — PASS.** Mechanical diff over all 175 required identifiers (151 entity fields + 78 body inputs + 30 query params + 14 path params, deduped) against standalone backticked tokens in §1–§3. Pass 1 found 0 under loose matching; the stricter pass-2 found 10 path-only identifiers (`batch_id`, `case_id`, `cdr_id`, `dispute_id`, `entry_id`, `factor_filing_id`, `filing_id`, `measurement_id`, `offer_id`, `order_id`) present only inside §4 path strings — repaired by rewriting §2.7 to key each of the 13 not-found codes to its named identifier. Pass 3: 0 missing.
- **Contract 2 — PASS after repairs.** The `applies_to` scope sweep caught real gaps, all fixed: `ERR_INVALID_INVOICE_STATE` was cited only for payments (added to issue, write-off and dispute-filing); `ERR_DISPUTE_SLA_EXPIRED` only for acknowledge (added to resolve); `ERR_INVALID_AUGMENT_ORDER_STATE` missing on complete; `ERR_INVALID_AGREEMENT_STATE` missing on agreement activate; `ERR_INVALID_TRUNK_GROUP_STATE` missing on trunk-group activate; `ERR_INVALID_FACTOR_FILING_STATE` not tied to review-vs-audit source states; `ERR_INVALID_DISPUTE_STATE` stated generically (now enumerates all four branches' source sets). Also added the explicit `EFFECTIVE → TERMINATED` arrow, the `RATED → RATED` / `INVOICED → INVOICED` re-rate self-loops, the `direction`-based selector for the 31-vs-27 CCS-per-trunk constant, and digit forms for the 90-day filing window and the 60.00 percent loss probability. All 102 endpoint `side_effects` were verified to mention every field they touch (only miss was the internal calculation name `negotiation_term_pinning`, correctly absent).
- **Contract 3 — PASS.** 1,148 backticked tokens in §3, zero starting with `/`, zero bare HTTP methods, zero method+path combinations.

One scaffold-fidelity correction worth flagging: my first draft of §3.4 invented a guard that traffic studies require `augment_status` to be `NONE` or `GROOMING_REVIEW`. The scaffold's validation only restricts `service_status` to `IN_SERVICE`, so I removed the fabricated constraint and now state explicitly that the `augment_status` dimension places no restriction on recording a study. §2.2 was confirmed byte-identical to `skills/prd-bench-doc-generator/section-2.2-response-structure.md`.

Orchestrator verification: `wc -lc` = 513 lines / 114,164 bytes; `## ` headings are exactly the five required; §4 table has exactly 80 `| GET |`/`| POST |` rows; §5 has exactly 69 `ERR_` rows; tail ends on a complete table row (not mid-sentence) — no truncation. Grep for `harder than expert`, `expert level`, `SCAFFOLD` in PRD.md returned zero hits, so the Step 2 difficulty instruction did not leak.

## Step 6: Generate Implementation — 2026-09-04T04:52:00.000Z

Implementation complete and verified.

## Modules written (`workspace/implementation/`)

| File | Lines | Role |
|---|---|---|
`app.py` | 70 | app factory, blueprint wiring, `ApiError`/`HTTPException` handlers, `PORT` default 10000 |
`start.sh` | 8 | guarded pip install + `exec python3 app.py` (chmod +x) |
`requirements.txt` | 1 | `flask>=2.0` |
`dec.py` | 51 | `Decimal` quantizers (ROUND_HALF_UP), `ceil_div` (ROUND_CEILING) |
`errors.py` | 97 | all 69 `error_id` → HTTP mappings, `ApiError` |
`envelope.py` | 120 | `meta`/`response_type`/`data` envelope, `req_` ids, ms timestamps, pagination |
`store.py` | 80 | 14 in-memory dicts, logical clock, `base_record`/`touch`/`ordered` |
`validation.py` | 199 | typed field extraction, `parse_float=Decimal`, scale enforcement |
`auth.py` | 142 | 8 roles, carrier-scope graph walks, SoD, both OCC guards |
`lookup.py` | 64 | 13 path resolvers with their distinct 404 ids |
`constants.py` | 121 | enums, 6 regexes, every calculation constant |
`services/reserve.py` | 114 | `reserve_provision` from scratch + append-only ledger |
`services/rating.py` | 173 | `jurisdiction_determination` + `access_charge_rating` |
`services/sizing.py` | 129 | `trunk_sizing_and_blocking` + `augment_install_window` |
`services/tariff.py` | 25 | half-open `[start, end)` coverage, window intersection |
`services/invoicing.py` | 57 | balance/dispute dimensions + §2.10 auto-close |
`routes/agreements.py` | 379 | negotiation, activation, termination cascade, reciprocal settlement |
`routes/trunks.py` | 288 | trunk lifecycle + traffic measurements |
`routes/disputes.py` | 285 | disputes, escalation, deadline sweep |
`routes/usage.py` | 236 | batches, CDRs, jurisdictionalize, rate |
`routes/invoices.py` | 205 | invoice create/issue/payments/write-off |
`routes/factors.py` | 197 | factor filings + 4-hop audit re-rate cascade |
`routes/recon.py` | 189 | reconciliation evaluate/adjust/accept |
`routes/augments.py` | 189 | augment accept/reject/complete/reverse |
`routes/tariffs.py` | 163 | tariff filing lifecycle with supersede truncation |
`routes/carriers.py` | 116 | registry + reserve summary |
`routes/ledger.py` | 29 | read-only ledger |
`routes/clock.py` | 24 | `POST /_clock/set_current_utc` (root, not under the prefix) |
| **total** | **3751** | |

## Coverage

- **Endpoints: 80/80.** I diffed the running app's URL map against the PRD's endpoint table programmatically — `diff` reports **IDENTICAL** (method + path, including `/_clock/set_current_utc` at root and the other 79 under `/interconnection`).
- **Entities: 14/14** dicts, all empty at boot — verified by listing every collection endpoint on a fresh process (`total_count=0` for all 14).
- **State machines: 13/13** — agreement, offer, trunk `service_status`, trunk `augment_status`, augment order, tariff, factor filing, batch, invoice ×3 parallel dimensions, dispute, reconciliation case.
- **Calculations: 9/9** — `jurisdiction_determination`, `access_charge_rating`, `reciprocal_compensation_settlement`, `trunk_sizing_and_blocking`, `augment_install_window`, `negotiation_term_pinning`, `dispute_sla_and_deemed_allowed`, `reserve_provision`, `record_exchange_reconciliation`.
- **Validations: 74** bands implemented in the fixed precedence order (auth → authz → path existence → schema → body refs → carrier scope → SoD → OCC → state → business a–f).
- **Errors: 69/69 reachable.** 56 raised by explicit `ApiError(...)` calls plus the 13 not-found ids raised through the `lookup._make` factory. The only non-catalogue ids are the framework fallbacks (`ERR_NOT_FOUND`, `ERR_METHOD_NOT_ALLOWED`, `ERR_INTERNAL`) and `ERR_RESERVE_LEDGER_ENTRY_NOT_FOUND`, which the PRD leaves unnamed for the `entry_id` segment.
- **Roles: 8/8**; `CarrierRepresentative`'s `X-User-ID` is the `Carrier.id` and scoping reaches through the full graph (403 on single reads/writes, filter on lists).

## Smoke test

Three servers launched on explicit high ports (18659/18660/18661) and each killed by its own captured PID — no pattern kills. `python3 -m compileall` clean.

Two multi-hop flows passed end to end (~60 assertions):
- carrier → 3 tariffs filed+approved → agreement → offer → OCC 412 on a stale version → accept → activate → trunk group → provision → activate → 5% blocking measurement auto-raising an augment order → accept → complete → factor filing → batch → 3 CDRs → jurisdictionalize → rate → invoice → issue → dispute → acknowledge → resolve SUSTAINED → recon case → evaluate → adjust → sweep → reciprocal settlement.
- Factor-audit re-rate cascade verified numerically: PIU 50/PLU 10 over 400 min → 200/160/40 → **3.48**; audited to PIU 80/PLU 5 → 320/60/20 → **3.78**, batch `rating_variant` PRELIMINARY→FINAL, `rerate_count` 1, invoice `billed_amount_usd` refreshed with `adjustment_count` 1.
- Reserve ledger sequence over the full lifecycle came out as `UNCOLLECTIBLE_ADJUSTMENT/INVOICE_CREATED (0.07)` → `.../FACTOR_AUDIT_RERATE (+0.01→0.08)` → `DISPUTE_PROVISION (2.00)` → `DISPUTE_RELEASE/DISPUTE_DEADLINE_SWEEP (−2.00)` → `.../INVOICE_PAYMENT_APPLIED (−0.02)` → `WRITE_OFF (0.78)` → `UNCOLLECTIBLE_ADJUSTMENT (−0.02→0.00)`, i.e. only buckets that actually moved, with the write-off pair in PRD order.
- Negative paths confirmed: `ERR_DUPLICATE_OCN` 409, `ERR_STALE_AGREEMENT_VERSION` 412, `ERR_CLOCK_MUST_ADVANCE` 422 (equal instant permitted), `ERR_DISPUTE_SLA_EXPIRED` 409, `ERR_SEGREGATION_OF_DUTIES` 403, `ERR_DISPUTE_AMOUNT_EXCEEDS_BALANCE` 422, `ERR_EFFECTIVE_DATE_NOT_REACHED` 409, `ERR_UNAUTHENTICATED` 401, `ERR_CARRIER_NOT_FOUND` 404, `limit=0`/`limit=101` → 422.
- Fresh-boot invariants: store empty, logical clock exactly `2026-08-01T00:00:00.000Z`, no disk persistence, no seeding.

Two PRD-fidelity fixes made during the pass: dropped an extra `carrier_id` from the reserve-summary read, and demoted `blended_rate_per_mou_usd` on the reconciliation case to a private field (it is a calculation intermediate, not a declared entity field). Isolation was honoured — no access to `test_suite/`, `test_helpers/`, either `SCAFFOLD_*_DESIGN.yaml`, or any sibling task.

Orchestrator note: Steps 5 and 6 were launched in two consecutive assistant messages rather than one, so physical isolation of `test_suite/` from the impl generator was not guaranteed by directory absence. The impl subagent was given an explicit hard prohibition on reading `test_suite/`, `test_helpers/`, and both design YAMLs, and reports honouring it; Step 5 had only just started when Step 6 launched, so no substantial test content existed to read.

## Step 5: Generate Unit Tests — 2026-09-04T06:10:00.000Z

Stage 2 is complete. All 13 test modules plus the Stage 1 infrastructure are in place at the task root.

## Files written (line counts)

`test_helpers/`
```
  20  __init__.py      595  api_client.py    176  api_errors.py
 230  assertions.py    194  constants.py     464  factories.py
 655  fixtures.py       96  test_users.py     83  types.py
```
`test_suite/`
```
  79  conftest.py
 306  test_01_carrier_registration.py            10 tests
 275  test_02_tariff_rate_book.py                 7
 534  test_03_agreement_negotiation.py           11
 243  test_04_agreement_lifecycle.py              6
 360  test_05_trunk_group_provisioning.py         9
 351  test_06_traffic_studies_and_sizing.py       8
 328  test_07_augment_order_lifecycle.py          7
 423  test_08_traffic_factor_filings.py           8
 462  test_09_usage_collection_and_rating.py     11
 594  test_10_invoicing_and_payment.py           12
 684  test_11_billing_disputes.py                12
 372  test_12_reconciliation_and_settlement.py    8
 336  test_13_reserve_provisioning_and_ledger.py  7
```
Total 7,860 lines; `pytest --collect-only` collects **116 tests** cleanly.

## Coverage against the two design indices
- **Queue A (§1.8 depth): 40 tests over all 20 instances — every instance has exactly 2 tests, none missed.**
- **Queue B (§1.9 breadth): 76 tests over 76 of the 77 non-stub instances.** The yaml's other 16 instances carry `excluded_because` (deferred to queue A) and were correctly left untagged; no stub was accidentally covered and no tag points at a non-existent instance.
- Every test carries exactly one trailing `Design:` line copied verbatim; every `PRD x.y:` quote is verbatim-greppable in `workspace/PRD.md`; no file mentions "scaffold". Audit output: `tests: 116, distinct tags: 96` → `OK`.

## Skipped / weakened instances
- **C41 `validations/dispute_against_a_written_off_invoice_is_refused` — SKIPPED (non-unique-derivability).** A WRITTEN_OFF invoice is already `CLOSED` under the §2.10 derivation, so §3.9's lifecycle gate yields `ERR_INVALID_INVOICE_STATE`, contradicting the demanded `ERR_INVOICE_ALREADY_WRITTEN_OFF`. This is the only non-stub instance with no test.
- **C60 — half emitted.** Only the `ERR_BATCH_ALREADY_INVOICED` claim; the `ERR_EMPTY_INVOICE` half is unreachable because §3.7 forbids jurisdictionalising an empty batch.

Individual claims dropped or corrected where the index contradicted the PRD (test still emitted): C23 final UNCOLLECTIBLE entry asserted as −0.45/balance 0.00; C24's "exactly 2 entries" claim dropped (§3.8 mandates two write-off entries); D16 asserts `rated_amount_usd == 0.00` rather than null; **D19** asserts the invoice's `dispute_status == RESOLVED` (PRD §3.9 states `DISPUTED → RESOLVED` on withdrawal; the index said `NONE`); **C30** asserts the unrated outbound batch holds 60.0000 minutes and that settlement still reports `outbound_minutes` 0.0000 (the index's "total_billable_minutes 0.0000" contradicts §3.7's CDR-append rule — the corrected form is a stronger test of the same filtering claim); **C35** drops the `adjustment_count == 1` claim, since §3.10 never increments it (only the factor-audit re-rate of §3.6 does).

Orchestrator verification: `test_helpers/` and `test_suite/` are both at the task root, and `find workspace -type d -name 'test_*'` returned nothing — no stray test directories under `workspace/`.

## Step 7: Test/Fix Iteration — 2026-09-04

Two 8-round parallel sweeps (116 tests each, `per-test-server`, `setsid nohup`).

- Iteration 1: 113/116 in all 8 rounds; the same three tests failed deterministically (no flakiness).
- Iteration 2: **116/116 in all 8 rounds** (`workspace/implementation/results.1..8.json`).

All three fixes landed in `test_suite/`; the implementation was not touched.

1. `test_04::test_negotiation_and_trunk_state_conflicts_each_report_their_own_id` — accepted an already-`ACCEPTED` offer on an `EFFECTIVE` agreement, so both §3.2 state rules fired at once and the error id was precedence-dependent (§2.7 band 9 does not order two state checks against each other). The offer-state conflict is now exercised on a live `PROPOSED` negotiation against a `SUPERSEDED` offer, where §3.2 refuses nothing about the agreement, so `ERR_INVALID_OFFER_STATE` is uniquely derivable and the exact-id assertion is preserved.
2. `test_04::test_agreement_termination_cascades_to_trunk_groups_and_open_orders` — two defects: `order["requested_trunks"]` is not a PRD field (§3.4 names `requested_additional_trunks`), and the torn-down group's `augment_status` was asserted as `NONE` although §3.2's teardown never names that dimension and §2.10 forbids inferring it. Field name corrected; the `augment_status` half of the dimension assertion dropped, `service_status == DISCONNECT_PENDING` kept.
3. `test_10::test_second_invoice_over_one_batch_is_refused` — asserted `ERR_BATCH_ALREADY_INVOICED`, which §2.7 makes unreachable: the first invoice moves the batch `RATED → INVOICED`, and band 9 (state preconditions) precedes band 10 (uniqueness), with §2.7 stating plainly that "a state conflict always beats a business-rule breach on the same request". Assertion corrected to `ERR_INVALID_BATCH_STATE`; the implementation's (dead but PRD-mandated) `ERR_BATCH_ALREADY_INVOICED` guard was left in place.

No test was deleted, no assertion weakened to an HTTP-status check, and no skip/xfail was added.

## Step 7: Run Tests and Iterate — 2026-09-04T06:30:00.000Z

Clean sweep achieved.

## Summary

**Iterations run: 2** (each a full 8-round parallel sweep, 116 tests, `per-test-server`, wrapped in `setsid nohup`).

- Iteration 1: 113/116 in **all 8** rounds — the same three tests failed in every round (deterministic, no flakiness anywhere in the suite).
- Iteration 2: **116/116 in all 8 rounds.** Final results files on disk: `workspace/implementation/results.1.json` … `results.8.json` (all written 06:01).

**Tests deleted: none.** No test failed the STEP 1 coverage / unique-derivability gate outright; all three were test-layer defects fixable toward greater PRD fidelity.

**Fixes applied to `test_suite/` (3, all in the test functions themselves):**

`test_suite/test_04_agreement_lifecycle.py`
1. `test_negotiation_and_trunk_state_conflicts_each_report_their_own_id` — the test accepted an already-`ACCEPTED` offer on an `EFFECTIVE` agreement, so §3.2's offer-state rule and its agreement-state rule fired on the same request and the returned id was pure precedence guesswork (§2.7 band 9 orders state checks against *other bands*, never two state checks against each other; both readings leave one PRD clause dead, so neither is uniquely derivable). Rather than relax to `validate_error_is_one_of`, I rebuilt the precondition so only one rule can fire: a second negotiation (own carrier via `setup_second_carrier`, `ensure_local_rate=False`) is driven proposal → counter → counter, leaving the agreement in `PROPOSED` — a status §3.2 explicitly does not refuse — and the *superseded* first offer is accepted by the non-offeror rep. The exact `ERR_INVALID_OFFER_STATE` assertion is kept intact.
2. `test_agreement_termination_cascades_to_trunk_groups_and_open_orders` — two bugs. (a) `order["requested_trunks"]` (the `KeyError`) is not a PRD field name; §3.4 names it `requested_additional_trunks`. (b) It asserted the torn-down group's `augment_status == "NONE"`; §3.2's teardown enumerates its effects and never names `augment_status`, and §2.10 states that neither status dimension implies anything about the other unless the document says so — so that half of the dimension assertion was uncovered (BRANCH-ASYMMETRIC SIDE EFFECT: `NONE` / unchanged `AUGMENT_ORDERED` / §3.4's `AUGMENT_BLOCKED` are all defensible readings). Per STEP 1c I kept the covered half (`service_status == "DISCONNECT_PENDING"`) and dropped only the uncovered one.

`test_suite/test_10_invoicing_and_payment.py`
3. `test_second_invoice_over_one_batch_is_refused` — asserted `ERR_BATCH_ALREADY_INVOICED`, which §2.7 renders unreachable: the first invoice moves the batch `RATED → INVOICED` (§3.8), and band 9 state preconditions precede band 10 uniqueness, with §2.7 saying plainly that "a state conflict always beats a business-rule breach on the same request". Corrected to the PRD-determined `ERR_INVALID_BATCH_STATE` (exact-id assertion preserved, §2.7 quote added to the docstring; the now-unused import was removed). No batch transition anywhere in the PRD returns an `INVOICED` batch to `RATED` — I checked the §3.6 factor-audit re-rate, which is explicitly a self-loop.

**Fixes applied to `test_helpers/`: none** — the failures traced to the test functions, not to fixtures/factories.

**Fixes applied to `implementation/`: none.** All three failures were test-layer defects. Notably the implementation's `ERR_BATCH_ALREADY_INVOICED` guard in `routes/invoices.py::create_invoice` is dead code under §2.7's ordering but PRD-mandated, so it was left in place rather than removed.

Orchestrator verification: all 8 `results.$i.json` files exist (each ~34.8 KB, mtime 06:01) and each reports `passed=116 / total=116 / failed=0`.

Step 8 decision: Step 7 applied 3 `test_suite/` fixes and ran 2 iterations, so the zero-iteration skip condition does NOT hold — Step 8 runs. Note that 0 `implementation/` fixes were applied, so the PRD/impl divergences Step 8 must consider are those revealed by the three test-layer corrections (the double-state-conflict precedence hole in §3.2, the `augment_status` silence in §3.2's teardown, and the batch state-vs-uniqueness precedence in §3.8), not by impl edits.

## Step 8: Finalize PRD — 2026-09-04T06:38:00.000Z

Both edits are in place.

## Result

**`workspace/PRD_FINALIZED.md`**

- PRD.md: 513 lines / 114,164 bytes → PRD_FINALIZED.md: 513 lines / 115,032 bytes. **Line delta 0.00%**, byte delta **+0.76%**. 2 lines revised (§3.2, twice), no lines added or removed, no new sections.

### Changes

- **§3.2 (acceptance) — revise — pinned the fixed order between §3.2's two acceptance state refusals: the agreement's `status` is examined before the offer's `status`, so a request wrong on both counts returns `ERR_INVALID_AGREEMENT_STATE` — `implementation/routes/agreements.py:229-233`.**
- **§3.2 (termination teardown) — revise — added the per-order decrement of the trunk group's `open_augment_order_count`, and pinned that the teardown leaves `augment_status` unchanged (explicitly *not* the `AUGMENT_ORDERED → AUGMENT_BLOCKED` move that §3.4's rejection performs) — `implementation/routes/agreements.py:316-329`.**

### No-edit findings (Step 7 items that were pure test-layer defects)

- Item 2(a) `requested_trunks` KeyError — PRD §3.4 and the impl both already use `requested_additional_trunks` (`routes/trunks.py:236`, `routes/augments.py:138`). Fixture/test bug only.
- Item 3 `ERR_BATCH_ALREADY_INVOICED` → `ERR_INVALID_BATCH_STATE` — already uniquely determined by §2.7 (band 9 before band 10) and §3.8's own clause ordering; `routes/invoices.py:49-54` checks batch state first. The dead-but-mandated uniqueness guard remains PRD-described as-is.

### Per-edit pre-edit search log

**Edit 1 — subject: order of evaluation among `accept_offer`'s state preconditions, and which error id an acceptance returns.**
(b) Paths enumerated: `grep -rn 'ERR_INVALID_OFFER_STATE|ERR_INVALID_AGREEMENT_STATE'` across the tree → `routes/agreements.py:134` (offer append), `:229/:233/:235` (accept), `:257` (activate), `:280` (withdraw), `:302/:307` (terminate), plus `errors.py:29-30` (both 409). Read `routes/agreements.py:200-340` in full. Also read the parallel two-state-check endpoints to check whether a *general* precedence rule would hold: `routes/augments.py:159-174` (reverse: the addressed order's own status is checked **before** the parent trunk group's status — the opposite nesting direction from accept), `routes/augments.py:68`, `:100`, `:128`, and `routes/invoices.py:170-193` (write-off checks `ERR_INVOICE_ALREADY_WRITTEN_OFF` before `lifecycle_status`).
(c) Adjustment: I had considered stating the rule generally in §2.7 as "the parent's state is checked first". `augments.py:169-174` falsifies that, so I **re-scoped the wording to §3.2's acceptance only** and framed it as an ordering "between themselves" rather than a system-wide band-9 tie-break. I also deliberately did **not** write "those are the only two refusals", because `agreements.py:234-236` raises a third `ERR_INVALID_AGREEMENT_STATE` for the offeror-accepts-own-offer case (checked last, no code named in PRD, untested by the suite and outside the Step 7 diff) — the sentence stays silent on it rather than excluding it.

**Edit 2 — subject: what the agreement-termination teardown does to a trunk group's augment dimension (`augment_status`, `open_augment_order_count`).**
(b) Paths enumerated: `grep -rn 'augment_status|open_augment_order_count|requested_additional_trunks'` over all non-test sources → every writer of `augment_status`: `routes/trunks.py:60` (birth → `NONE`), `:227` (`GROOMING_REVIEW`), `:229` (`AUGMENT_BLOCKED`), `:247` (`AUGMENT_ORDERED`); `routes/augments.py:108` (reject → `AUGMENT_BLOCKED`), `:148` (complete → `NONE`), `:183-184` (reverse → `GROOMING_REVIEW`, guarded on current value being `NONE`); and every writer of `open_augment_order_count`: `routes/trunks.py:248` (+1), `routes/augments.py:109`, `:149` (−1), `routes/agreements.py:327` (−1, the teardown), with the reader/gate at `routes/trunks.py:172` (disconnect completion requires 0) and `services/sizing.py:118` (posture reads `AUGMENT_BLOCKED`). Confirmed `routes/agreements.py:294-334` never assigns `augment_status`. Also grepped PRD_FINALIZED for every existing `open_augment_order_count` and `augment_status` mention (lines 203, 209, 215, 233, 241, 243, 245) to check for contradiction.
(c) Adjustment: the first draft asserted the trunk group "is left with no open augment work", an editorial universal; I dropped it in favour of the bare per-order decrement. I also added the explicit contrast with §3.4's rejection cascade so the new "keeps whatever value it was carrying" sentence cannot be read back into §3.4 line 241 (direct rejection *does* move `AUGMENT_ORDERED → AUGMENT_BLOCKED`), and phrased it as "keeps whatever value it was already carrying" rather than naming any specific value, which stays true for the `AUGMENT_BLOCKED`, `GROOMING_REVIEW`, `AUGMENT_ORDERED` and `NONE` starting points alike — including trunk groups already `DISCONNECTED` that the teardown skips entirely.

Orchestrator verification: both files are 513 lines; `diff` shows exactly 2 changed lines, both in §3.2 — consistent with the reported minimal patch.

## Step 9: Complete PRD — 2026-09-04T07:35:00.000Z

Orchestrator note on execution shape: Step 9 was run as **three sequential subagent passes over disjoint partitions of `implementation/`** rather than one subagent, because the implementation is 3,750 lines across 28 modules and a single-pass scan reliably degenerates into a byte-identical copy of the input PRD (the scan never actually runs). Each pass edited `workspace/PRD_COMPLETED.md` in place with targeted `Edit` calls; pass 1 owned the `cp` from `PRD_FINALIZED.md`. Partitions: pass 1 = app/start.sh/requirements/dec/errors/envelope/store/validation/auth/lookup/constants + routes/{carriers,tariffs,agreements,trunks,clock} + services/tariff; pass 2 = routes/{augments,factors,usage} + services/{rating,sizing}; pass 3 = routes/{invoices,disputes,recon,ledger} + services/{reserve,invoicing}.

### Pass 1 of 3 — infra + carriers/tariffs/agreements/trunks/clock

- `PRD_FINALIZED.md` 513 lines / 115,032 bytes → `PRD_COMPLETED.md` 514 lines / 125,299 bytes (**+1 line, +10,267 chars**); the extra line is one new bullet inside the existing §2.2 success-envelope bullet list. No new sections.
- **26 changes: 20 ambiguity-pins, 6 mismatch-revisions.**
- §2.1 — revise — ambiguity — whitespace-only header counts as empty, values are trimmed, and an `X-User-Role` outside the eight names is `ERR_UNAUTHENTICATED`/401 rather than 403 — `auth.py:48-56`
- §2.1 — insert — ambiguity — carrier scope **narrows** flat cross-entity collection reads (10 named collections) instead of refusing; refusal applies to single reads, writes and parent-scoped nested lists — `auth.py:68-71`, `agreements.py:218`, `trunks.py:103,287`
- §2.2 — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric chars — `envelope.py:11,21`
- §2.2 — revise — ambiguity — `api_request_timestamp` comes from real wall-clock time, not the logical clock — `envelope.py:36-44`
- §2.2 — insert — ambiguity — money/minutes/percentages/rates serialize as JSON **numbers** with no scale padding (`0.0`, `0.1`); documented-null fields emit `null` — `envelope.py:47-56`
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` is 422, empty string takes the default, `offset` beyond `total_count` is an empty page not an error — `envelope.py:95-113`
- §2.3 — insert — ambiguity — filters are optional, conjunctive, exact-string-match, unvalidated against enums; empty filter ignored; `augment_triggered` accepts `true/1/false/0`; scoping applied after filters, before `total_count` — `validation.py:190-199`, `envelope.py:116-120`
- §2.4 — insert — ambiguity — free-text reasons/notes not named as resource fields (agreement `withdrawal_reason`/`termination_reason`, tariff `withdrawal_reason`) are retained internally and absent from responses; named ones (`rejection_reason`, `dispute_reason`) are returned — `envelope.py:53`, `agreements.py:289,312`, `tariffs.py:161`
- §2.5 — insert — ambiguity — sub-millisecond input precision is retained for comparisons but **truncated** when rendered — `validation.py:166`, `envelope.py:30-33`
- §2.7 step 3 — revise — ambiguity — unresolvable `entry_id` yields `ERR_RESERVE_LEDGER_ENTRY_NOT_FOUND` (404), a fourteenth code — `lookup.py:50-57`
- §2.7 step 4 — insert — ambiguity — declared scale is a maximum; integer fields accept zero-fraction numbers (`24.0`); no numeric field accepts bool/string; strings must be non-empty after trimming; `null` on required = violation, on optional = default; full accepted timestamp grammar; empty body = `{}`, malformed/non-object body = 422 — `validation.py:20-30,47-62,87-147,150-179`
- §2.7 step 4 — insert — ambiguity — undeclared body fields are ignored, so §2.6's "must not send a version" is a client contract, not a server refusal — `validation.py` (no unknown-key rejection anywhere)
- §3.1 — revise — **mismatch** — "six financial figures" → **five** (impl initialises exactly the five named) — `carriers.py:41-45`
- §3.1 — insert — ambiguity — agreement `effective_date` is unconstrained vs the clock at creation; only compared at activation — `agreements.py:54`
- §3.1 — revise — ambiguity — an offer's `transit_traffic_allowed` is **required** (unlike the optional flag on the opening ask) — `agreements.py:128`
- §3.1 — insert — ambiguity — after the first append `offer_type` is unconstrained; only alternation and the round ceiling bind — `agreements.py:152-155`
- §3.1 — insert — ambiguity — fixed local order: agreement status → rate cap → round ceiling → party sequence — `agreements.py:133-155`
- §3.2 — revise — ambiguity — an acceptance by the offering side is refused with `ERR_INVALID_AGREEMENT_STATE` — `agreements.py:234-236`
- §3.2 — insert — ambiguity — accept/activate/withdraw/terminate all answer with the **agreement**, not the offer — `agreements.py:248,269,291,334`
- §3.3 — revise — ambiguity — `poi_clli_code` is 11 chars of uppercase letters **or digits** — `constants.py:64`
- §3.3 — insert — ambiguity — `transit_traffic_allowed` read from the agreement's current value (ask before execution, pinned after); parent agreement status places **no** constraint on requesting a trunk group — `trunks.py:38-42`
- §3.4 — revise — **mismatch** — version bumps: trunk group always bumps (no-action included); agreement bumps unconditionally in the augment-ordered branch (pending count moved), only on an actual posture change in the blocked branch, never in no-action/grooming — `trunks.py:225-255`
- §3.5 — revise — **mismatch** — approval's fixed local order displaces §2.7's bands: body-ref → `FILED` → `ERR_EFFECTIVE_DATE_NOT_REACHED` → `ERR_TARIFF_WINDOW_OVERLAP` → superseded `EFFECTIVE` → superseded-window containment; also spells the two superseded-precondition codes — `tariffs.py:100-133`
- §3.7 (reciprocal-settlement paragraph) — insert — ambiguity — a null pinned rate yields `net_settlement_usd` 0.00 and a null echoed rate while mode/ratio still report — `agreements.py:357,370`
- §4 preamble — insert — ambiguity — trailing slash insignificant (`strict_slashes = False`); Description-cell filters are additive to `limit`/`offset` — `app.py:35`
- §4 rows — revise — 1 mismatch + 9 ambiguity — tariff withdraw description corrected from "a filed or effective rate" to FILED-only (**mismatch**, `tariffs.py:156`); filter parameters named for the 10 list endpoints in the partition
- §5 preamble — insert — **mismatch** — four uncatalogued identifiers documented: `ERR_NOT_FOUND` 404, `ERR_METHOD_NOT_ALLOWED` 405, `ERR_INTERNAL` 500, `ERR_RESERVE_LEDGER_ENTRY_NOT_FOUND` 404 — `app.py:46-59`, `lookup.py:55`

Partition walk (pass 1): all 17 files walked. Findings from `app.py`, `envelope.py`, `validation.py`, `auth.py`, `lookup.py`, `constants.py`, `routes/carriers.py`, `routes/tariffs.py`, `routes/agreements.py`, `routes/trunks.py`. No findings from `start.sh`, `requirements.txt`, `dec.py`, `errors.py` (catalogue verified identical to §5, 69/69), `store.py`, `routes/clock.py`, `services/tariff.py`.

### Pass 2 of 3 — augments/factors/usage + rating/sizing services

- 514 lines / 125,299 bytes → 514 lines / 130,347 bytes (**+5,048 bytes, no new lines**).
- **19 changes: 17 ambiguity-pins, 2 mismatch-revisions.**
- §3.4 (augment sizing/facility test) — revise — mismatch — the POI facility test's augment-order leg spans **every** sibling trunk group at the agreement+POI, not only the `PROVISIONED`/`IN_SERVICE` ones the `provisioned_trunks` leg is narrowed to — `services/sizing.py:51-59`
- §3.4 (reversal) — insert — ambiguity — `augment_status` → `GROOMING_REVIEW` is conditional on the dimension still reading `NONE`; any other value is left as it stands — `routes/augments.py:183-184`
- §3.4 (reversal) — insert — ambiguity — the agreement's `capacity_posture` is **not** recomputed by a reversal (row is still touched, `version` +1) — `routes/augments.py:187-188`
- §3.4 (reversal) — insert — ambiguity — `reversal_reason` is a required non-empty string retained for audit only, not a returned field of the order; the trunk-group precondition names `ERR_INVALID_TRUNK_GROUP_STATE` — `routes/augments.py:164,172-174,179`
- §3.4 (reversal) — insert — ambiguity — the order's own status is tested before the trunk group's within the state-precondition band — `routes/augments.py:169-174`
- §3.6 (supersession) — insert — ambiguity — `ERR_FACTOR_FILING_DISPUTE_OPEN` sits in the uniqueness/overlap sub-band, i.e. after the regulatory factor-sum ceiling; all prior filings for the pair are scanned in `created_at` ASC — `routes/factors.py:50-59`
- §3.6 (review) — insert — ambiguity — a missing `dispute_reason` on a `DISPUTE` decision is a step-4 schema violation answering `ERR_INVALID_REQUEST`, evaluated before the state precondition; a reason sent with `ACCEPT` is ignored — `routes/factors.py:122-136`
- §3.6 (audit) — insert — ambiguity — state precondition precedes the sum ceiling; `dispute_reason` and the stored audited pair are never cleared by an audit, a later `ACCEPT`, or a supersession — `routes/factors.py:151-162`, `routes/factors.py:26-33`
- §3.6 (cascade hop 1) — insert — ambiguity — re-jurisdictionalisation is a full re-run including factor re-selection, and the re-rate runs with the effective-rate requirement relaxed, so it never raises `ERR_NO_EFFECTIVE_TARIFF_RATE`; an uncovered jurisdiction contributes 0.00 and leaves its records' `rated_amount_usd` null — `routes/factors.py:176-177`, `services/rating.py:125-133,148-151,160-163`
- §3.6 (cascade hop 2) — insert — ambiguity — `payment_status`/`dispute_status` are untouched and the §2.10 close derivation does not fire, so an invoice re-rated to a zero open balance keeps its payment status and stays `ISSUED` — `routes/factors.py:186-193`
- §3.6 (cascade hops 2–4) — revise — mismatch — hops 2–4 run **once per re-rated batch**, so a carrier with two invoiced batches sees two reserve recomputations (`version` +1 each) and one `UNCOLLECTIBLE` entry per moved recomputation; a batch with no `ISSUED` invoice stops after hop 1; the entry's `invoice_id` names the invoice hop 2 refreshed — `routes/factors.py:169-197`
- §3.7 (jurisdiction determination) — insert — ambiguity — the empty-batch refusal also carries `ERR_INVALID_BATCH_STATE`, immediately after the `SUBMITTED` check — `routes/usage.py:212-214`
- §3.7 (rating variant) — insert — ambiguity — a batch with no indeterminate minutes (`factor_source` `SIGNALING_ONLY`) is `PRELIMINARY`; only `AUDITED` yields `FINAL` at rating, and a null `traffic_factor_filing_id` means no audit can promote it — `services/rating.py:171`
- §4 (6 cells) — insert — ambiguity — created_at ASC ordering and filter sets pinned for `/trunk-groups/{id}/augment-orders`, `/trunk-augment-orders`, `/traffic-factor-filings`, `/usage-batches`, `/usage-batches/{id}/call-detail-records`, `/call-detail-records`

Partition walk (pass 2): all 5 files walked, all produced findings — `routes/augments.py` (all 7 handlers), `routes/factors.py` (5 handlers + `_refresh_effective` + `_rerate_cascade`), `routes/usage.py` (8 handlers), `services/rating.py` (8 functions), `services/sizing.py` (10 functions). Accept-path and complete-path orderings, the `ERR_BATCH_PERIOD_OVERLAP` ordering, rating formulas/rounding scales, blocking/sizing/install-window/collision-inclusivity and posture precedence were all found already uniquely pinned — no edit needed.

### Pass 3 of 3 — invoices/disputes/recon/ledger + reserve/invoicing services

- 514 lines / 130,347 bytes → 514 lines / 136,437 bytes (**+6,090 bytes, no new lines**).
- **27 changes: 20 ambiguity-pins, 7 mismatch-revisions.**
- §2.10 — insert — ambiguity — credits promote `payment_status` to PAID only from UNPAID/PARTIALLY_PAID, so a WRITTEN_OFF invoice is never re-promoted by a credit — `services/invoicing.py:22-27`
- §2.10 — insert — ambiguity — `open_balance_usd` is recomputed arithmetically and is never floored at zero — `services/invoicing.py:15-19`
- §2.10 — insert — ambiguity — the close derivation is one-way ISSUED→CLOSED and never reverts once satisfied — `services/invoicing.py:49-54`
- §2.11 — revise — mismatch — the blanket "`amount_usd` is a signed delta and `balance_after_usd` the post-movement balance" rule qualified: the WRITE_OFF entry carries the abandoned balance and the *pre*-recomputation bucket balance — `services/reserve.py:97-102`
- §2.11 — revise — mismatch — removed the claim that `invoice_id` is null for carrier-level re-measurements; no such operation exists and every emission passes an invoice id — `services/reserve.py:76`
- §2.11 — insert — ambiguity — bucket/entry emission order pinned: WRITE_OFF first, then DISPUTED_REVENUE, then UNCOLLECTIBLE — `services/reserve.py:97-113`
- §2.11 — insert — ambiguity — `entry_type` derivation pinned: DISPUTE_PROVISION vs DISPUTE_RELEASE by delta sign; uncollectible movement is always UNCOLLECTIBLE_ADJUSTMENT — `services/reserve.py:104-113`
- §2.11 — insert — ambiguity — `RECONCILIATION_ADJUSTMENT` is a declared entry type that no code path emits — `services/reserve.py:97-113` (with `constants.py` enum)
- §2.11 — insert — ambiguity — `open_balance_usd` contributes only for ISSUED + UNPAID/PARTIALLY_PAID, while `disputed_amount_usd` contributes for any ISSUED invoice regardless of payment dimension — `services/reserve.py:31-40`
- §3.8 — revise — mismatch — dropped the unconditional INVOICE_CREATED ledger entry on issue; entries are written only when a bucket balance actually moves — `routes/invoices.py:135` + `services/reserve.py:96-113`
- §3.8 — revise — mismatch — write-off ledger entry shape corrected to the pre-mutation open balance captured before recompute — `routes/invoices.py:196-205`
- §3.8 — insert — ambiguity — payment `amount_usd` carries no lower bound at the schema step; only the balance ceiling is enforced — `routes/invoices.py:144`
- §3.8 — insert — ambiguity — write-off checks WRITTEN_OFF (409 `ERR_INVOICE_ALREADY_WRITTEN_OFF`) *before* the ISSUED lifecycle check — `routes/invoices.py:179-186`
- §3.8 — insert — ambiguity — `rate_authority_filing_id` resolves by ranking `(-subtotal, rate_element)` and is null when no jurisdiction has an EFFECTIVE filing — `routes/invoices.py:26-39`
- §3.8 — insert — ambiguity — `due_date` is accepted as a date with no temporal constraint relative to the clock or period — `routes/invoices.py:41-60`
- §3.8 — insert — ambiguity — payment sets PAID vs PARTIALLY_PAID by comparing the recomputed balance to zero, then runs the close derivation — `routes/invoices.py:160-162`
- §3.9 — revise — mismatch — removed "enforced as a fiscal rule rather than as a range check on the field"; a negative `credited_amount_usd` is rejected at the schema step as `ERR_INVALID_REQUEST` — `routes/disputes.py:148`
- §3.9 — insert — ambiguity — dispute dimensions are recomputed from the full dispute set, so `dispute_status` stays DISPUTED while any second dispute is open and never returns to NONE once one has been filed — `services/invoicing.py:31-45`
- §3.9 — insert — ambiguity — filing checks WRITTEN_OFF before the lifecycle precondition — `routes/disputes.py:41-46`
- §3.9 — insert — ambiguity — escalation is ungated on the SLA clock and never runs the close derivation, so escalating a dispute on a CLOSED invoice cannot reopen it — `routes/disputes.py:189-216`
- §3.9 — insert — ambiguity — the response body of a dispute transition is the dispute row, not the invoice — `routes/disputes.py:143-187`
- §3.9 — insert — ambiguity — sweep ordering pinned as `filed_at` then the standard created_at/insertion tiebreak — `routes/disputes.py:250-266`
- §3.9 — insert — ambiguity — swept disputes record `resolved_by_user_id = "SYSTEM_SWEEP"`, and a full credit can move `payment_status` to PAID — `routes/disputes.py:267-273`
- §3.10 — revise — mismatch — deleted "a negative adjustment cannot arise from a valid request"; the agreed-minutes interval is `min(ours, theirs)..max(ours, theirs)`, so `agreed > ours` is legal and produces a signed negative `adjustment_amount_usd`, posted rather than refused or clamped — `routes/recon.py:133-148`
- §3.10 — revise — mismatch — removed the "rated batch" precondition on case opening; the implementation imposes no batch-status gate — `routes/recon.py:27-32`
- §3.10 — revise — mismatch — qualified the ledger sum invariant to movement entries, with the write-off entry standing outside the sum — `services/reserve.py:97-113`
- §3.10 — insert — ambiguity — the blended rate is stored on an internal `_`-prefixed key (never serialized), is 0.000000 when agreed minutes are zero, and adjustment refusals order `ERR_INVOICE_NOT_ISSUED` before `ERR_INVOICE_ALREADY_WRITTEN_OFF` — `routes/recon.py:151-159`
- §4 (7 cells) — revise — ambiguity — reserve-ledger list filters pinned to `carrier_id`/`invoice_id`/`reserve_bucket`/`entry_type` with no carrier scoping; invoice-list filter set and dispute/recon endpoint descriptions aligned; stale "rated batch" precondition dropped — `routes/ledger.py:22-29`, `routes/invoices.py:99-112`, `routes/recon.py:86`

Partition walk (pass 3): all 6 files walked end to end, each yielding findings — `routes/invoices.py` 7, `routes/disputes.py` 7, `routes/recon.py` 6, `routes/ledger.py` 1, `services/reserve.py` 6, `services/invoicing.py` 4. Pass 3 declined one tempting global pin ("a transition always returns the path-named resource") because `routes/agreements.py:248` makes that universal false; the returned entity was pinned locally in §3.9 and §3.10 instead.

### Step 9 totals and orchestrator verification

- **72 changes across the three passes: 57 ambiguity-pins, 15 mismatch-revisions.**
- `PRD_COMPLETED.md` = 514 lines / 136,437 bytes, vs `PRD_FINALIZED.md` 513 lines / 115,032 bytes (**+1 line, +21,405 bytes, +18.6%**).
- `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md`; `diff` reports **71 changed lines** — the scan genuinely ran.
- Structural integrity intact: 29 markdown headings, the five required `## ` sections at lines 3/11/178/352/440, exactly 80 `| GET |`/`| POST |` endpoint rows, exactly 69 `ERR_` catalogue rows, and the file still terminates on the complete final row `` | `ERR_INVALID_CREDIT_AMOUNT` | 422 | `` — no truncation.
- No stray `worklog*` file anywhere under the task tree other than the canonical `worklog.md` at the task root.
- The 8 clean-sweep `results.$i.json` files remain on disk in `workspace/implementation/`. Step 9 touched only `PRD_COMPLETED.md`, so the 116/116 × 8-round result stands unchanged.

**Pipeline complete.**
