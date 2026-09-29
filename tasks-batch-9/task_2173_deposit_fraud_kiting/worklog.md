## Step 1: Create task directory — 2026-08-29T00:00:00.000Z

Created `tasks/task_2173_deposit_fraud_kiting/` and `tasks/task_2173_deposit_fraud_kiting/workspace/` (next index after task_2172).

## Step 2: Generate scaffold — 2026-08-29T15:26:00.000Z

All three scaffold artifacts are written and lint-clean.

## Files

- `SCAFFOLD.yaml` (§1.0–§1.7, no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

No sibling task directory was read, listed, or grepped — the design comes only from the scenario text plus the skill spec.

## Verdict block (pasted verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2173_deposit_fraud_kiting/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2173_deposit_fraud_kiting/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2173_deposit_fraud_kiting/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    49
  §1.1 entities declared:     11
  §1.8 instances scanned:     18
  §1.9 instances scanned:     45
  Calls scanned (§1.8+§1.9):  518

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Shape

Above the Expert band as requested: 11 entities, 49 endpoints, 45 error codes, 9 calculations, 10 state machines, 2 OCC concurrency rules, 39 ordered validations. Profile is `compliance_audit` × `graph_constraint`, **flat** topology, **parallel** state-machine shape, **segregation_of_duties** role model — all the §0.3 axes flagged as under-represented.

Difficulty spine (all nine §0.5 rules, 2 instances each = 18):
- **Dual-variant** on two different domains: account risk `PROVISIONAL_AT_OPEN` 77 vs `REFRESHED` 47; kiting `STRICT` 66 vs `INCLUSIVE` 70 on identical data — the two land on opposite sides of the 70 case-opening threshold.
- **Combinatorial** in two different modes: mode (a) five-input score with a link cap and confidence gate (73 with 6 or 8 links); mode (b) pinned rounding order — `38`/`48`, where sum-then-round gives `39`/`49`.
- **Non-linear machines**: DepositAccount carries genuinely independent `lifecycle_status` × `access_posture` dimensions; HoldOverrideReview has a `SUBMITTED ⇄ RETURNED_FOR_INFO` revision loop (plus FundingSource and FraudCase and BsaReferral loops).
- **Two depth-4 cascades** from different triggers (override execute → review → hold → account → fraud case; MULE substantiation → account → holds → reviews).
- **Two priority conflicts** on different category pairs (`state` vs `business_fiscal`; `business_safety` vs `business_referential`), each proving the loser rule is live rather than absent.
- **Two boundaries** on different metrics/endpoints (risk_score exactly 60 via account-links; empty qualifying set / zero-division guard via kiting-scan).
- **Two cross-entity dependencies** on different pairs (DepositItem→DepositAccount; HoldOverrideReview→CheckHold).
- **Two overlap rules with different interval semantics**: half-open release windows on an account (adjacency allowed) vs closed preservation windows on a customer (mandatory 3-day buffer).
- **Two conserved quantities**: depositor `ledger_balance_cents` (deposit → override release → return) and `ledger_balance_cents - charged_off_amount_cents` (book → reverse).

Every numeric assertion is a pre-computed literal (`38`, `48`, `66`, `70`, `105000`, `103501`, `577501`, `2026-08-11T00:00:00Z`, …), and the corner file's 45 executable instances + 9 stubs trigger all 45 error codes.

Two things worth flagging for the next stage: the surface is deliberately larger than the Expert band (49 endpoints / 45 errors), so the PRD doc-generator is at elevated risk of the section-truncation failure mode — generate and verify section counts rather than trusting a green test sweep. Also, `POST /deposit-fraud/_clock/set_current_utc` fixes the startup clock at `2026-08-01T00:00:00Z`, and every fixture date in both design files is anchored to it.

## Step 3: Copy shared files — 2026-08-29T15:27:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2173_deposit_fraud_kiting/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-29T15:38:00.000Z

PRD generated at `workspace/PRD.md` (86 KB, 466 lines), written incrementally in seven appends so no section was truncated.

**Structure**: §1 Introduction (3 paras) → §2 with 10 subsections (RBAC, fixed response envelope, pagination/filtering, identity+versioning, logical clock, money/rounding, OCC, cascade propagation, funds-conservation invariant, validation ladder) → §3 with 9 domain-derived workflow subsections (onboarding & risk scoring, funding verification, deposit intake & availability ladder, early-release review, ATO posture & step-up, kiting detection, fraud case lifecycle + BSA referral, charge-off/recovery/reversal, subpoena & preservation) → §4 endpoint table (4 columns) → §5 error table (2 columns). No audit footer.

**Verified counts** (machine-checked against SCAFFOLD.yaml after writing):

- Endpoints: **49/49** paths present in the §4 table, 0 missing; roles column from `endpoints[].roles`.
- Error codes: **45/45** rows in §5, and all 45 also mentioned in §2/§3 narrative (0 orphaned).
- Calculations: **9/9** expressed in prose — `new_account_risk_score` (both `PROVISIONAL_AT_OPEN`/`REFRESHED` variants), `ato_indicator_score`, `check_hold_schedule` (5-step ordered ladder, strict edges at 30 days / 552,500 cents), `hold_override_loss_exposure` (round-per-line-then-sum, then second rounding), `kiting_cycle_score` (STRICT/INCLUSIVE variants, created_at tie-break), `charge_off_pricing` (tier from `base_net_cents`, inclusive upper bounds), `recovery_waterfall` (fee-then-principal, all-or-nothing), `bsa_aggregate_amount`, `account_funds_invariant`.
- State machines: **10/10** covered (both DepositAccount dimensions, FundingSource, DepositItem, CheckHold, HoldOverrideReview, FraudCase, ChargeOff, SubpoenaRequest, BsaReferral); every state value in the scaffold appears verbatim in backticks — 0 missing.
- Validations: **39/39** — all `error_id`s reachable from prose, `applies_to` sets enumerated (e.g. `ERR_HOLD_NOT_ACTIVE` across all four override endpoints), and the full priority ladder rendered as an explicit 19-rank ordered list in §2.10, including the 41→42→43 ordering nuance and the deliberate charge-off reverse gate/guard split.
- RBAC matrix: all **6** roles named with `X-User-ID` / `X-User-Role` semantics; `AccountHolder` documented as `entity_backed:Customer`, the other five as opaque with the eight actor-capture fields listed.

**Hard contract reports**

```
Field coverage check:
- entities[].fields: 105 required, 105 present, 0 missing
- endpoints[].request_body/input: 56 required, 56 present, 0 missing
- endpoints[].query_params (limit/offset/filters): included above, 0 missing
- kiting-scan & clock response fields (cycle_length, qualifying_item_count,
  deposited_cents, uncollected_cents, uncollected_ratio_bps, detected,
  current_utc): 7 required, 7 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 39 checked, 39 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed
  (write_endpoint + expected_check_hold_version / expected_account_version
   + ERR_STALE_CHECK_HOLD_VERSION / ERR_STALE_ACCOUNT_VERSION + 412), 0 missing
- state_machines[].transitions: 51 checked, 51 fully expressed, 0 missing
- calculations[]: 9 checked, 9 fully expressed, 0 missing
- validations[] conditions: 39 checked, 39 matchable to error_id, 0 missing
- endpoints[].side_effects / applies_to: 49 checked, 49 expressed, 0 missing
- entities[].fields[] structured content: 105 checked, 105 reconstructible, 0 missing
- sibling-branch symmetry: 7 groups checked, 7 with equal prose density, 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 876
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

§2.2 was pasted byte-identical from `section-2.2-response-structure.md` (verified by substring match). No fuzzy/approximating words.

The withheld files `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped, or referenced.

## Step 6: Generate implementation — 2026-08-29T15:58:00.000Z

Implementation complete and verified.

## What was built

`workspace/implementation/`

| File | Contents |
|---|---|
| `start.sh` | Guarded `pip install`, `exec python3 app.py`, `PORT` default 10000 |
| `app.py` | Flask entry, blueprint registration, error handlers, `0.0.0.0:$PORT` |
| `core.py` | Logical clock, in-memory `Store`, error catalog (45 codes), envelope helpers, auth decorator, body/query validators, path lookups |
| `calc.py` | All 9 calculations + derived aggregates + shared cascades |
| `serial.py` | 11 entity serializers |
| `routes_a/b/c.py` | 49 endpoints, split by resource group |

Storage is in-memory dicts only; **no seeding** — a fresh `Store()` is empty on every boot and the clock starts at `2026-08-01T00:00:00Z`. Route table verified programmatically against SCAFFOLD §1.5: **49/49 match, 0 missing, 0 extra**. Boots and serves HTTP in ~2s via `bash start.sh`.

## Verification

Five in-process suites (~230 assertions) all pass, covering: risk scoring under both variants, funding retry/BLOCKED loop, the hold-type ladder with both strict boundaries, per-line-then-sum exposure rounding (proved distinct from sum-then-round via 160¢ holds → 8, not 9), the 4-hop execute cascade, MULE vs KITING substantiation cascades, 2- and 3-account kiting cycles with STRICT/INCLUSIVE divergence, charge-off tiers/waterfall/reversal, preservation-window buffer, segregation of duties, and the §2.10 validation ladder. A store-wide sweep confirms `available + held == ledger` for every account and `outstanding_loss_cents >= 0` for every charge-off.

## Judgment calls worth flagging

Three PRD ambiguities resolved against §2.10's rank-9 code ordering (which matches SCAFFOLD file order) rather than §3's sentence order — the two sources disagree:

1. **`ERR_HOLD_NOT_ACTIVE` before `ERR_REVIEW_NOT_SUBMITTED`/`ERR_REVIEW_NOT_APPROVED`** on submit/decide/execute.
2. **`ERR_CASE_NOT_SUBSTANTIATED` before `ERR_REFERRAL_INVALID_STATE`** on referral submit.
3. **`account_role`** has no declared enum anywhere in PRD or scaffold. Accepts a synonym set (`DEPOSITING`/`DEPOSITOR`/`DEPOSIT`/`ACCOUNT`/… vs `DRAWEE`/`DRAWN_ON`/…, case-insensitive) and rejects anything else with `ERR_INVALID_REQUEST`.

Two behavioural rules derived from prose rather than the state table:

- The ATO score ladder **never de-escalates** a posture (§3.5) — a LOCKED account scoring 40–74 stays LOCKED; only a supervisor reset or a correct step-up moves it down.
- **Every** verification attempt re-runs the REFRESHED risk score (§3.1), not just a matching one.

Account `version` bumps use a dirty-check over stored fields, with forced bumps where the PRD states one explicitly (access-review, step-up-response, charge-off proposal, and the hold on override-review creation).

## Step 5: Generate unit tests — 2026-08-29T16:05:00.000Z

Test infrastructure and suite are generated and audited clean.

## What was produced

**`test_helpers/`** (9 modules, ~1,650 lines)
- `types.py` — 11 entity TypedDicts (all `common_fields: true`, so all carry `id`/`created_at`/`updated_at`/`version`), 25 status/enum classes, `UserRole`, plus a `KitingScanResult` shape.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint; all 49 PRD §4 endpoints covered.
- `api_errors.py` — all 45 error ids + HTTP map, registered via `set_error_http_status_map`.
- `assertions.py` — per-entity assertions, `assert_funds_conservation` / `assert_net_bank_position` / `assert_charge_off_invariants`, plus timestamp helpers.
- `constants.py`, `factories.py`, `test_users.py` (opaque-role constants + `make_account_holder_headers(customer_id)` for the one `entity_backed:Customer` role, threaded through every ownership-gated call).
- `fixtures.py` — 6 tiers of composite setup.

**`test_suite/`** — `conftest.py` + 10 domain-named files, **81 tests**, all collecting under pytest.

## Coverage audit (scripted, re-runnable)

- 18/18 difficulty instances → **≥2 tests each** (36 tests).
- 45/45 non-stub corner instances → **≥1 test each**.
- 9 `excluded_because:` stubs — every `difficulty_instance` cross-reference resolves; no placeholder tests emitted.
- Every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line, verbatim from the source yaml; **0 untagged, dual-tagged, or dangling tags**.
- Every quoted PRD citation checked against a whitespace-normalized PRD.md — **0 non-verbatim quotations**. No `skip`/`skipif`/`xfail` anywhere.

## Notable findings

- **No instance failed the PRD-first filter.** §2.10 states the full 19-rank validation ladder explicitly; §2.7 names both OCC fields *and* both rejection error ids; §3.4 pins the round-per-line-then-sum order in prose.
- Two assertions deliberately instant-based rather than string-exact: `opened_at` / `hold_release_at` / `closure_scheduled_at` compare parsed UTC instants.
- `assert_customer` runs on the GET re-read rather than the 201 body.
- All literal expected values recomputed independently and agree with the design indices (STRICT 66 vs INCLUSIVE 70; 38/48 vs sum-then-round 39/49; tier-1 fee 5000 at exactly 100000 base net vs tier-2 3500 at 100001).

## Step 7: Test and fix loop — 2026-08-29T16:12:00.000Z

Done. The task was already clean on the first sweep.

## Summary

**Iterations run:** 1 (the 8-round parallel sweep passed on the first pass — no fix loop was entered).

**Sweep result:** all 8 concurrent rounds `passed == total == 81`, `failed == 0`, `errors == 0`, `skipped == 0`. Union of failing tests across rounds: empty. No flakiness surfaced — all 8 rounds were identical, so no timing-sensitive bug (race window, fixture ordering, port collision) escaped.

**Tests deleted:** none. The diagnostic protocol (STEP 0 → 3) was never triggered, since STEP 0 produced an empty union set.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

### Non-vacuity check

Because a green first sweep can also mean a vacuous or leak-tuned suite rather than a complete one, the sweep was mutation-tested before exiting. Four single-constant mutations were applied to disposable copies of `workspace/implementation/calc.py`, each targeting a *different* PRD boundary rule, and each was run as its own full round:

| Mutation | PRD rule attacked | Result |
|---|---|---|
| `LARGE_DEPOSIT_CENTS` 552500 → 552499 | §3.3 strict `>` edge on the large-deposit hold class | 80/81 — caught |
| `RETURN_RATE_BPS["CHECK"]` 275 → 274 | §3.4 per-line return-rate pricing feeding the authority gate | 79/81 — caught |
| `RECOVERY_FEE_TIER_1_MAX_CENTS` 100000 → 99999 | §3.8 *inclusive* upper bound on the fee tier | 78/81 — caught |
| `LINK_CONFIDENCE_MIN_BPS` 6000 → 6001 | §3.1 `is_risk_bearing` at exactly 6,000 bps | 80/81 — caught |

All four were detected, and each by the test that specifically names that rule (e.g. `test_recovery_fee_tier_is_selected_from_base_net_not_the_grossed_up_total`, `test_link_at_exactly_six_thousand_basis_points_lifts_the_band_to_high`). The green sweep reflects a genuinely complete implementation, not a suite that fails to bite. Mutation copies were made outside the task tree and deleted; the implementation is byte-identical to its pre-check state.

### Other verifications

- 81 tests collected == 81 tests reported; zero `skip`/`xfail`/`pytest.mark` anywhere in `test_suite/` or `test_helpers/`.
- Storage is in-memory only — `core.py:121` is a bare `db = Store()` with no startup seeding.
- The 8 `results.${i}.json` artifacts are intact in `workspace/implementation/`.

## Step 8: Finalize PRD — SKIPPED — 2026-08-29T16:13:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes. No `PRD_FINALIZED.md` produced; Step 9 starts from `PRD.md`.

## Step 9: Complete PRD — 2026-08-29T16:20:00.000Z

Done. `workspace/PRD_COMPLETED.md` written.

**Counts** — PRD.md: 465 lines / 86,253 chars → PRD_COMPLETED.md: 465 lines / 89,396 chars (**+3,143 chars**). 19 edits on 17 lines; no new sections, no new paragraphs, no line-count change.

**Ambiguity-pins: 15. Mismatch-revisions: 4.**

- §2.3 Pagination — revise — ambiguity — list ordering ties on identical `created_at` (the common case under a frozen logical clock) resolved by server insertion order — `core.py:536-537` (`sort_rows` keys on `(created_at, _seq)`)
- §2.3 Pagination — revise — ambiguity — `account_role` has no declared enum; pinned the case-insensitive synonym sets (`DEPOSITING`/`DEPOSITOR`/`DEPOSIT`/`ACCOUNT`/`DEPOSITING_ACCOUNT`/`DEPOSITED_INTO` vs `DRAWEE`/`DRAWN_ON`/`DRAWEE_ACCOUNT`/`DRAWN`), anything else `ERR_INVALID_REQUEST` — `routes_b.py:49-57,140-148`
- §2.4 Versioning — insert — ambiguity — a row rescored/repriced/rebalanced as a *secondary* effect does not advance `version`/`updated_at` when every stored field lands on its prior value — `calc.py:98-109` (`bump_if_dirty`)
- §2.10 rank 9 — insert — ambiguity — parent-resource gate wins inside rank 9: `ERR_HOLD_NOT_ACTIVE` before `ERR_REVIEW_NOT_SUBMITTED`/`ERR_REVIEW_NOT_APPROVED`; `ERR_CASE_NOT_SUBSTANTIATED` before `ERR_REFERRAL_INVALID_STATE` — `routes_b.py:360-363,384-387,413-416`, `routes_c.py:423-426`
- §3.2 Funding — insert — ambiguity — declaring a funding source has no lifecycle/posture gate — `routes_a.py:285-308`
- §3.3 Settlement — insert — ambiguity — a `return_reason` sent with `CLEARED` is still enum-validated but ignored and not recorded — `routes_b.py:180-184,195-198`
- §3.4 Submission — revise — ambiguity — hold check precedes review-status check — `routes_b.py:360-363`
- §3.4 Decision — revise — ambiguity — same precedence on decide — `routes_b.py:384-387`
- §3.4 Execution — revise — ambiguity — same precedence on execute — `routes_b.py:413-416`
- §3.4 Execution — revise — ambiguity — `adjusted_exposure_cents` compared is the *stored* figure; execute never reprices — `routes_b.py:420`
- §3.5 Access review — revise — ambiguity — `indicator_codes` is required (may be empty, may not be absent/null) — `routes_c.py:67-71`
- §3.5 Posture ladder — revise — **mismatch** — the 40–74 branch as written de-escalated a `LOCKED` account, contradicting the ladder's own closing sentence; pinned to escalation-only — `routes_c.py:86-94` (`POSTURE_RANK` guard)
- §3.6 Choosing the cycle — revise — ambiguity — a cycle needs at least two distinct accounts; a self-drawn item is never a candidate — `calc.py:349-351`, `calc.py:51`
- §3.6 What a detection does — insert — **mismatch** — the scan returns the figure set (not the created case) with HTTP 200 even when it opens a case, against §4's blanket 201-on-create rule — `routes_c.py:145-181`
- §3.6 Duplicate suppression — insert — **mismatch** — `ERR_ACCOUNT_NOT_ACTIVE` (rank 9) precedes `ERR_DUPLICATE_OPEN_CASE` (rank 8) on this endpoint, inverting §2.10 — `routes_c.py:142-155`
- §3.7 Referral filing — revise — ambiguity — case gate before referral-status gate — `routes_c.py:423-426`
- §3.7 `aggregate_amount_cents` — revise — **mismatch** — sums items by their own `account_id` only; the drawn-on side is excluded — `calc.py:451-457`
- §3.8 Booking — insert — ambiguity — `APPROVED → BOOKED → REFERRED_TO_RECOVERY` in one request advances the charge-off `version` by exactly 1 — `routes_c.py:558-572`
- §3.8 Recovery postings — revise — ambiguity — `amount_cents` is an integer of at least 1 — `routes_c.py:581`
- §3.8 Reversal — revise — ambiguity — `reversal_reason` required and typed, no non-blank/length rule, persisted nowhere — `routes_c.py:616`
