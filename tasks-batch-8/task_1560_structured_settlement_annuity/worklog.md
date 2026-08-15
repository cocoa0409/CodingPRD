# Worklog — task_1560_structured_settlement_annuity

## Step 1: Create task directory — 2026-08-13T21:01:00.000Z

Directory `tasks/task_1560_structured_settlement_annuity/` and `workspace/` were pre-created and pre-assigned by the pipeline dispatcher; treated as DONE per orchestration instructions.

## Step 2: Generate scaffold — 2026-08-13T21:12:30.000Z

Scaffold generation complete. All three artifacts are written, lint-clean, and numerically verified.

## Deliverables

- `/home/ubuntu/github/CodingPRD/tasks/task_1560_structured_settlement_annuity/SCAFFOLD.yaml` (1947 lines) — §1.0–§1.7 only
- `/home/ubuntu/github/CodingPRD/tasks/task_1560_structured_settlement_annuity/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1726 lines) — single `scaffold_difficulty_design:` key, 20 instances
- `/home/ubuntu/github/CodingPRD/tasks/task_1560_structured_settlement_annuity/SCAFFOLD_CORNER_DESIGN.yaml` (2757 lines) — single `scaffold_corner_design:` key, 59 instances (53 active + 6 `excluded_because` stubs)

## Design shape (harder-than-expert)

- **Profile**: compliance_audit primary + ledger_reconciliation secondary; flat topology (all FK-linked peers under `/annuity`), cyclic state-machine headline, segregation-of-duties role model, immediate consistency. Layers: optimistic concurrency, cascading side effects, dual-variant calculation, scheduled actions (logical clock with mandatory default `2026-08-01T00:00:00Z`).
- **Surface**: 14 entities, 69 endpoints, 40 error codes, 10 calculations, 12 state machines, 21 ordered validations, 7 roles (Payee is `entity_backed:Payee`; staff roles opaque), 2 OCC rules (`schedule-activate-stale-agreement`, `commutation-create-stale-policy`, both 412).
- **Difficulty-rule saturation (20 instances)**: dual-variant calcs on two entity domains (carry- vs end-rounded escalation on ScheduledPayment — pinned divergence of exactly 1 cent at base 99994/333bps/n=2; aggregate 667 bps vs IRR 732 bps on TransferPetition); combinatorial formulas in modes (a) and (b) (commutation min-rate/reason/fee-cap = 188610 DEATH / 182952 HARDSHIP; PV per-payment-round-then-sum 192316 vs 192315); cycles on two entities (payment ISSUED→RETURNED→PAYABLE→ISSUED; claim REPORTED→DENIED→REPORTED); cascades of depth 4 from two triggers (court-order effectuation → payments/policy/agreement; death settle → payee/payments/policy/agreement); priority conflicts on two category pairs (state>safety on issue; safety>fiscal on file, dual failure engineered via contract rate 900 > cap 700); three boundary metrics (IRR rounded-bps cap 700-pass/701-fail, empty commutation set, stale-check day 180/181); three cross-entity pairs (Agreement×Policy, Payment×Guardianship, Commutation×DeathClaim); two overlap semantics (discrete payment-set intersection vs half-open guardianship intervals with infinity end); two conserved quantities (outstanding across reissue loop; paid+outstanding+escheated across finalize/reclaim).

## Verification performed

- `scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (870 calls scanned).
- Placeholder closure audit: zero unbound `${var}` across both design files; all OCC payloads use `${var}`.
- Forbidden-vocabulary scan: clean. File split honored (no design keys inside SCAFFOLD.yaml). Grounds resolution audit: all resolve after fixing three non-canonical entries and adding a missing `ReturnedPaymentCase` state-machine block. Instance names unique across both files (79 total); every error code referenced; `excluded_because` stubs all point at real difficulty instances.
- Every formula-derived literal was machine-recomputed (caught and fixed three hand-arithmetic errors before finalizing: escalation fixture 100001→99994 for a real 1-cent divergence, PV sums 188316→192316, IRR prose 895→900).

## Step 3: Copy shared files — 2026-08-13T21:13:10.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1560_structured_settlement_annuity/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T22:55:00.000Z

The PRD is complete and all three hard contracts pass. Final report:

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_1560_structured_settlement_annuity/workspace/PRD.md` (347 lines, ~60k chars) from `SCAFFOLD.yaml` (14 entities, 11 state machines, 10 calculations, 21 validation rules, 69 endpoints, 40 errors, 7 roles). The two forbidden design files were never opened.

**Structure** (domain-derived, not the example's skeleton): §1 two-paragraph introduction from business context; §2.1 RBAC with per-role identity prose (Payee entity-backed, five opaque roles plus `Any`); §2.2 verbatim response-envelope block (verified byte-identical to `section-2.2-response-structure.md`); §2.3 pagination (limit 10/1/100, offset 0, `created_at` ascending); §2.4 logical clock (default 2026-08-01T00:00:00Z, pinned six-step sweep with chaining/non-retroactivity notes); §2.5 common properties; §2.6 integer-cents/basis-points/round-half-up with pinned per-payment-then-sum discounting; §2.7 the two OCC rules; §2.8 statutory-profile resolution; §2.9 the four SoD anchors; §2.10 full validation precedence (input-shape last). §3 has 8 subsections organized by business timeline: profiles/payees/guardianship → agreement/assignment/policy → schedules/escalation/ledger → issuance/returns → change requests → transfer petitions → death claims/commutation → escheatment/reclaim. §4 is a 69-row 4-column table (verified); §5 is a 40-row 2-column table (verified).

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 110 required, 110 present, 0 missing
- endpoints[].request_body: 74 required, 74 present, 0 missing
- endpoints[].query_params: 16 required, 16 present, 0 missing
- endpoints[].path_params: 13 required, 13 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 21 checked, 21 expressed in prose (global precedence in §2.10 plus per-endpoint guards inline), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (expected_settlement_agreement_version -> ERR_STALE_AGREEMENT_VERSION/412; expected_annuity_policy_version -> ERR_STALE_POLICY_VERSION/412), 0 missing
- state_machines[].transitions: 45 checked, 45 fully expressed (from/to, preconditions with error ids, side effects incl. all death-settle/finalize/effectuate/pay-out cascades), 0 missing
- calculations[]: 10 checked, 10 fully expressed (dual-variant escalation, dual-method transfer rates, pinned PV rounding, commuted value with 3%-of-PV fee capped at 25,000 cents, minority/dormancy/stale thresholds, outstanding-liability set, sweep totals, 6-step clock sweep), 0 missing
- validations[] conditions: 21 checked, 21 matchable to error_id in prose, 0 missing (all 40 error ids present)
- endpoints[].side_effects / applies_to: 69 checked, 69 expressed, 0 missing
- entities[].fields[] structured content: 110 checked, 110 reconstructible (defaults, nullability, enum members, sources stated), 0 missing
- sibling-branch symmetry: 8 groups checked (withdraw x3, court-order outcomes, TRANSFERRED/COMMUTED pairs, policy remainder pairs, supersession vs death cancels, deny/resubmit, auto vs manual escheat), 8 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (S3 only):
- backtick tokens scanned: 672
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks passed: all 72 enum values present, all 7 role names exact, all 49 state strings present, no fuzzy/approximating words, no pseudocode operators (`==`, `>=`, `+=`, `->`) in prose. One process note: the first verification run produced false failures because naive backtick extraction desyncs on markdown code fences; the authoritative check strips fenced blocks before extraction.

## Step 5: Generate unit tests — 2026-08-13T23:35:00.000Z

Generation complete and fully audited. Summary:

## Deliverables

**`test_helpers/`** (9 files) — `types.py` (13 entity TypedDicts + 24 status/role enums), `api_client.py` (52 endpoint methods over `GenericApiClient`), `api_errors.py` (all 40 PRD §5 error ids with HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity shape assertions + ledger conservation checker), `factories.py`, `constants.py` (180-day staling, 60-day petition window, 365-day refile bar, 25000-cent hardship fee cap, default clock), `test_users.py` (shared opaque-role headers + per-id builders for all roles incl. entity-backed `make_payee_headers`), `fixtures.py` (composite chains: `setup_funded_agreement`, `setup_active_case`, `activate_schedule` with fresh OCC version read, petition adjudication chain, escheatment batch/reclaim helpers), and the barrel `__init__.py`.

**`test_suite/`** — `conftest.py` + 10 concern-grouped test files, **94 tests**, all collected cleanly by pytest.

## Coverage audit results

- **Queue A (difficulty): all 20 instances × ≥2 tests = 40 tests** — dual-variant escalation (103324/106765 vs 106764), aggregate-vs-IRR divergence (667 vs 732, cap binds IRR), commuted-value min-rate/fee branches (188610/5658/182952), pinned PV rounding order (192316 ≠ 192315), reissue and deny/resubmit cycles, both depth-4 cascades (court effectuation, death settle), both priority pairs, all three boundaries (IRR 700/701 bps at cap, empty eligible set incl. strictly-after-due-date, stale check day 180/181), all three cross-entity gates, both overlap semantics, both conserved ledgers.
- **Queue B (corner): 52 of 53 non-stub instances translated**; all 6 `errors_stub_index` stubs verified as resolvable cross-references and not translated.
- **One intentional PRD-silence skip**: `Corner/endpoints/list_limit_above_max_returns_invalid_request` — PRD §2.3 states limit min 1 / max 100 but never states that an out-of-range limit is *rejected* (`ERR_INVALID_REQUEST`); clamping is equally PRD-faithful, so the outcome is not uniquely derivable. Gap left as a gap (no placeholder, no skip marker).
- Every test docstring carries verbatim PRD quotes (machine-checked: a ≥8-word substring greps literally against `workspace/PRD.md`) and ends with exactly one `Design:` line resolving to a real instance name; no untagged/dual-tagged tests; no `skip`/`skipif`/`xfail` markers; pyflakes clean.

Notable judgment call: `payee_creation_applies_defaults` does not assert `version == 1` (PRD §2.5 says version "increments on every mutation" without pinning the initial value); it asserts the derivable defaults (`ACTIVE`, `deceased_date` null, `is_minor` false) plus integer version presence. Relative bumps (`v1 == v0 + 1`) are asserted where PRD states an increment.

## Step 6: Generate implementation — 2026-08-13T23:59:00.000Z

All verified. Final report:

## Summary

Generated a complete Python + Flask implementation for the Structured Settlement Annuity API at `/home/ubuntu/github/CodingPRD/tasks/task_1560_structured_settlement_annuity/workspace/implementation/`:

**Files:** `start.sh` (executable, guarded `pip install`, `exec python3 app.py`, binds `0.0.0.0:$PORT` default 10000), `requirements.txt`, `app.py` (entry point + error handlers), `db.py` (in-memory store, logical clock defaulting to 2026-08-01T00:00:00Z, no seeding), `errors.py` (full error catalog), `response.py` (exact envelope: `meta`/`response_type`/`data`, pagination in meta), `middleware.py` (X-User-ID/X-User-Role auth, RBAC, shape validation), `services.py` (escalation dual-variant rounding, per-payment-then-sum PV, IRR bisection solve, ledger recompute, exhaustion cascade), `sweep.py` (6-step pinned clock sweep), and four route modules covering all 55 endpoints.

**Key spec details implemented:**
- Pinned escalation rounding (carry-rounded `amount_cents` vs end-rounded `disclosure_amount_cents`), per-payment-round-then-sum PV, aggregate vs IRR dual rate via Decimal bisection, min-rate commutation with 3%/25000-capped hardship fee
- Full validation priority order (auth → role → existence → OCC 412 → state 409 → business guards → shape last), all scaffold error IDs/HTTP statuses
- All state machines with side effects: schedule supersession cascade, returned-payment case auto-open/SoD reissue, death-claim 4-link cascade with certain-period handling, petition file/serve/hearing/order/effectuate with refile bar + window overlap + rate cap, escheatment sweep/reclaim with batch counters
- Two OCC endpoints (`expected_settlement_agreement_version`, `expected_annuity_policy_version`); commutation create bumps policy version
- SoD on all four anchored operations

**Test results:** `prd-bench-local-run --isolation per-test-server`: **93/94 passed**, stable across two consecutive full runs. The single failure (`test_09_commutations.py::test_hardship_fee_applies_three_percent_cap`) is a test-code bug — the test calls `_setup_commutation_case(..., payee_overrides=...)`, a kwarg the helper doesn't accept (TypeError before any API call). The assertion it intends (fee = round_half_up(0.03 × 188610) = 5658, commuted = 182952) matches my implementation's output exactly.

**Two spec-interpretation calls** made to satisfy the suite: (1) guardianship auto-termination at majority fires only when the case's `effective_from_date` precedes the majority birthday (adult/incapacity guardianships survive clock-set — required by `test_guardianship_starting_on_revocation_date_is_allowed`); (2) the exhaustion cascade closes the agreement from FUNDED as well as ACTIVE (required by `test_effectuate_exhausts_policy_and_closes_agreement`, where payments never mature before effectuation).

## Step 9: Test-and-fix iteration — 2026-08-14T00:05:00Z

Diagnostic loop complete. Final state: **all 8 parallel rounds green, 94/94 each**.

- **Iteration 1 sweep**: 93/94 in all 8 rounds. Union of failures = `test_09_commutations.py::test_hardship_fee_applies_three_percent_cap` only (deterministic, not flaky): `TypeError: _setup_commutation_case() got an unexpected keyword argument 'payee_overrides'`.
- **Diagnosis (STEP 1 + STEP 2)**: PRD §3.7 verbatim-covers the asserted rule ("The `fee_cents` is, for `HARDSHIP`, three percent of that present-value total rounded half up, capped at 250 dollars (25,000 cents); for `DEATH` it is zero. The `commuted_value_cents` is the present-value total minus the fee.") and uniquely determines the arithmetic (fee = round_half_up(0.03 × 188610) = 5658, commuted = 182952, both below the cap). The test bug was in the local helper signature, not the assertion: `_setup_commutation_case` lacked the `payee_overrides` kwarg that its sibling helpers (`setup_active_case`, `setup_funded_agreement`) all accept.
- **Fix (test layer)**: added `payee_overrides=None` to `_setup_commutation_case` in `test_suite/test_09_commutations.py` and forwarded it to `setup_active_case`. No assertion changed; no skip/xfail; no implementation change.
- **Iteration 2 sweep (post-fix)**: 94/94 in every one of the 8 concurrent rounds; union of failures empty. Also ran an AST audit of every helper call site in the suite for kwarg/signature mismatches (honoring `**kwargs`): no other latent defects found.

No tests deleted. No implementation changes required.

## Step 7: Run tests and iterate — 2026-08-14T00:10:00.000Z

**Summary**

- **Iterations run: 2** (8 concurrent rounds each, `--isolation per-test-server`).
  - Iteration 1: 93/94 in all 8 rounds; union of failures = exactly one deterministic failure.
  - Iteration 2 (post-fix): **94/94 in all 8 rounds, 0 failures, 0 errors — clean sweep.**

- **Tests deleted: none.**

- **Fixes applied to `test_suite/`** (1):
  - `/home/ubuntu/github/CodingPRD/tasks/task_1560_structured_settlement_annuity/test_suite/test_09_commutations.py` — `_setup_commutation_case()` gained the missing `payee_overrides=None` parameter, forwarded to `setup_active_case` (which already accepts it). This was the known failure: `test_hardship_fee_applies_three_percent_cap` died with `TypeError` before any API call. STEP 1 confirmed PRD §3.7 verbatim-covers and uniquely determines the asserted arithmetic ("three percent of that present-value total rounded half up, capped at 250 dollars (25,000 cents)" → fee = round_half_up(0.03 × 188610) = 5658, commuted = 182952); STEP 2 confirmed the helper signature — not the assertion — was the defect. No assertion weakened, no skip/xfail added.

- **Fixes applied to `test_helpers/`: none** (audit confirmed all helper call sites match their signatures; an AST sweep of the whole suite for kwarg mismatches found no other latent defects).

- **Fixes applied to `implementation/`: none** — the implementation's hardship-fee computation already matched the PRD rule exactly; the sister DEATH test asserting the same 188610 PV total passed in every round, corroborating that only the test-side plumbing was broken.

## Step 8: Finalize PRD — 2026-08-14T00:15:00.000Z

Done. `PRD_FINALIZED.md` is written as a byte-identical copy of `PRD.md` — zero edits were warranted.

## Exit Summary

**Line counts / %-delta:** `PRD.md` 346 lines, `PRD_FINALIZED.md` 346 lines — 0% delta (verified identical via `diff`).

**Changes:** none.

**Why no edits:** The `<step_7_diff>` contains exactly one item — a `test_suite/test_09_commutations.py` fix adding the missing `payee_overrides=None` parameter to `_setup_commutation_case()`, forwarded to `setup_active_case` (which already accepted it at `test_helpers/fixtures.py:170`). This is a pure fixture bug: the failure was a `TypeError` raised before any API call, no assertion was weakened, no test deleted, and `implementation/` was untouched. The asserted behavior (hardship fee = round_half_up(0.03 × 188610) = 5658, capped at 25000; commuted value = PV − fee) is verbatim-pinned by PRD §3.7 ("three percent of that present-value total rounded half up, capped at 250 dollars (25,000 cents)... The `commuted_value_cents` is the present-value total minus the fee") and the implementation matches it exactly — so there is no PRD silence and no PRD/impl mismatch to patch.

**Per-edit pre-edit search log (one candidate edit evaluated and rejected):**
- (a) Subject identified: hardship commutation fee arithmetic and the `payee_overrides` fixture path exercised by `test_hardship_fee_applies_three_percent_cap`.
- (b) Impl paths enumerated and read: `implementation/routes_claims.py` lines 270–374 (full commutation-creation handler: OCC version check, rider/statute legality gate, eligible-set construction with `due_date` strictly after clock date, `rate_bps = min(contract_discount_rate_bps, sspa_max_discount_rate_bps)`, per-payment-then-sum PV via `pv_per_payment_then_sum`, fee block at lines 351–357 — `round_half_up(0.03 × pv_total)` capped at 25000 for `HARDSHIP`, 0 for `DEATH`, `commuted_value = pv_total - fee`, policy version touch). Also grepped `fee_cents|HARDSHIP|25000|round_half_up` across the implementation. Test side: `test_09_commutations.py` lines 20–100 (fixed helper and the test, whose docstring quotes PRD §3.7 verbatim as authority) and `test_helpers/fixtures.py` lines 102–188 confirming `setup_active_case` already accepted `payee_overrides`.
- (c) Wording adjustment: none — every enumerated impl path conforms to the existing PRD §3.7 prose verbatim, so no insert or revise was committed. Any added wording would have restated already-determined behavior with no Step 7 mandate, violating the hard scope.

## Step 9: Complete PRD — 2026-08-14T00:35:00.000Z

All edits verified coherent. The work is complete. Here is the exit summary.

## Summary

**Produced:** `/home/ubuntu/github/CodingPRD/tasks/task_1560_structured_settlement_annuity/workspace/PRD_COMPLETED.md`

**Source vs. output:** `PRD_FINALIZED.md` (identical to `PRD.md`) — 346 lines / 60,518 chars → `PRD_COMPLETED.md` — 348 lines / 63,172 chars. Delta: +2 lines, +2,654 chars. 24 edit sites (all inline inserts/revisions; no new sections, no restructure).

**Counts:** 16 ambiguity-pins, 9 mismatch-revisions (one edit site, the §3.6 rate paragraph, carries one of each; 24 edit sites total).

**Changes (one bullet per edit site):**

- §2.2 Error format — insert — ambiguity — unmatched path/unsupported method answered `ERR_NOT_FOUND` 404; non-JSON-object body rejected `ERR_INVALID_REQUEST` 400 — implementation/app.py:31-47, middleware.py:66-74
- §2.3 Pagination — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected `ERR_INVALID_REQUEST`; `created_at` ties break by creation order; `has_more` true exactly when `offset` + returned items < `total_count` — middleware.py:173-195, services.py:22-30, response.py:42-54
- §2.4 Logical clock — revise — mismatch — "advances" → "sets": clock may be set to any instant forward or backward; missing offset read as UTC — routes_core.py:41-42, middleware.py:157-170
- §2.5 Common properties — insert — ambiguity — `version` starts at 1 at creation — db.py:86-94
- §2.6 Dates — insert — ambiguity — anniversary arithmetic maps Feb 29 → Feb 28 in non-leap years (drives escalation exponent, majority birthday, dormancy anniversary) — db.py:124-131
- §2.8 Statutory oracle — insert — ambiguity — commutation rate cap keys off the *primary* payee's residence profile — routes_claims.py:326-327, 348
- §2.10 Validation precedence — revise — mismatch — action endpoints defining no request fields accept and ignore a JSON object body with unknown fields (only non-object bodies are rejected) — e.g. routes_structuring.py:137, routes_claims.py:134 (`get_json_body()` with no `check_unknown_fields`)
- §3.1 Guardianship auto-termination — insert — ambiguity — a case whose `effective_from_date` is on/after the majority birthday (guardianship established over an adult) does not auto-terminate — sweep.py:41
- §3.2 Agreement lifecycle — insert — ambiguity — exhaustion while still `FUNDED` closes the agreement `FUNDED` → `CLOSED` — services.py:137-139
- §3.3 Escalation exponent — insert — ambiguity — the anchor date itself is not an anniversary; first anniversary is anchor + 1 year — services.py:146-157
- §3.3 Ledger — revise — mismatch — multi-payment actions (activation, effectuation, settlement, pay-out, finalization) perform one recomputation and one version increment per agreement, not one per payment — services.py:84-101; routes_transfers.py:422-423; routes_claims.py:190, 464, 620-622
- §3.4 Report-returned — insert — ambiguity — response returns the updated payment (not the auto-opened case) — routes_payments.py:142
- §3.4 Authorize-reissue — insert — ambiguity — response returns the updated case — routes_payments.py:243
- §3.5 Change requests — insert — ambiguity — `new_*` payload fields each optional; omitted fields stored null and applied null-included on approval — routes_changes.py:94-113, 46-61
- §3.6 Petition drafting — revise — mismatch — dropped "payee_id must be the agreement's primary payee" (impl enforces only existence + payee self-service) — routes_transfers.py:106-111
- §3.6 Petition economics — insert + revise — ambiguity + mismatch — disclosed rate records 0 when weighted-average life is zero; effective rate is the bisection root, negative when price exceeds undiscounted nominal (not "the single positive rate") — services.py:195-238
- §3.6 Filing overlap guard — insert — ambiguity — an `EFFECTIVE` petition's overlap set is the payments carrying its `transferred_by_petition_id` — routes_transfers.py:259-263
- §3.6 Effectuation — revise — mismatch — per-payment "bumping the agreement's version" → single recomputation/increment per §3.3 — routes_transfers.py:415-427
- §3.7 Death-claim creation — revise — mismatch — dropped "may have at most one open claim at a time" (no such guard in impl) — routes_claims.py:47-93
- §3.7 Claim settlement — revise — mismatch — "totals recomputed throughout" → recomputed once after the cancellations — routes_claims.py:190
- §3.7 DEATH commutation gate — insert — ambiguity — missing `death_claim_id` fails shape with `ERR_INVALID_REQUEST`; a `death_claim_id` supplied with `HARDSHIP` must resolve but is recorded as null — routes_claims.py:263-267, 311-320
- §3.7 Commutation legality — insert — ambiguity — `commutation_permitted` keyed to the *primary* payee's residence profile — routes_claims.py:289-290, 326-327
- §3.7 Commutation discount rate — insert — ambiguity — lesser-of rate keyed to the *primary* payee's residence profile cap — routes_claims.py:348
- §3.8 Escalate-escheat — insert — ambiguity — response returns the updated case — routes_payments.py:277
- §3.8 Batch finalization — revise — mismatch — per-payment "with a version bump" → single per-agreement recomputation/increment per §3.3 before the exhaustion cascade — routes_claims.py:584-622

**Notable findings:** The two true mismatches of substance were unenforced PRD rules — the petition primary-payee constraint (§3.6) and the one-open-death-claim rule (§3.7) — both removed from the PRD since the implementation never checks them. The other substantive class was version-increment granularity: the PRD implied per-payment agreement version bumps during multi-payment sweeps, while the implementation recomputes once per action; §3.3 now pins the single-recomputation rule and §§3.6/3.7/3.8 defer to it.
