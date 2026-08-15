# Worklog — task_1708_overdraft_program_fee_governance

## Step 1: Create Task Directory — 2026-08-14T09:39:00.000Z

Pre-created and pre-assigned by the pipeline launcher: `tasks/task_1708_overdraft_program_fee_governance/workspace/`. Treated as DONE per instructions.

## Step 2: Generate Scaffold — 2026-08-14T10:41:00.000Z

All checks pass. The scaffold package is complete and lint-clean.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1708_overdraft_program_fee_governance/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no design keys inside; verified)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`, 19 instances
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`, 54 active instances + 19 `excluded_because` stubs

**Surface counts**: 11 entities (OverdraftProgram, DepositAccount, OptInElection, AccountTransaction, PostingBatch, OverdraftFee, FeeWaiverRequest, WaiverRequestItem, ProgramChangeNotice, EducationOffer, RegulatoryReport) · 51 endpoints · 31 error codes · 10 state machines · 6 calculations · 13 ordered validation priorities · 2 OCC concurrency rules · 7 roles (AccountHolder is `entity_backed:DepositAccount`; all others opaque).

**Difficulty design (19 instances, all 9 rules ≥2)**: dual-variant = posting-order fee count (HIGH_TO_LOW 2 fees/7000¢ vs CHRONOLOGICAL 1 fee/3500¢, identical −2500 ledger) + provisional/settled report revenue (7000 vs 3500); combinatorial = mode (a) cap/de-minimis interplay, mode (b) per-item-then-sum waiver rounding (3039 vs 3038), mode (c) pinned items-before-fees working-balance order (observable −700 mid-flight ledger); non-linear machines = election revoke/reinstate cycle + waiver deny→appeal→higher-band cycle; cascades = settle (depth 4: fee post → ledger → day-count → restrict+sustained fee → steering offer) and reversal (depth 3); priority conflicts = state-beats-fiscal and safety-beats-temporal; boundaries = de-minimis exact −500 at seal, day-count == 3 at settle; cross-entity = transaction×election pay/return gating, account×waiver close blocking; temporal overlap = half-open notice windows (adjacency allowed) vs closed-interval report tiling (gap forbidden); invariants = ledger+assessed−waived conservation vs charged_off+recovered==original.

**Verification**: `scaffold_lint.py` verdict (verbatim): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (51 endpoints, 11 entities, 19 §1.8 + 54 §1.9 instances, 758 calls scanned). Additional scripted audit: 92 instance names unique across both files, all `grounds:` resolve to declared §1.1–§1.7 elements, every error code referenced outside its catalog entry, all `excluded_because` targets exist, no forbidden concurrency vocabulary.

**Design decisions worth recording**:
- Flat topology with `/v1` prefix; every FK reverse-reachable via filtered-list GETs (single-item GETs added for OptInElection and WaiverRequestItem to register their collection segments for lint check (f)).
- Logical clock endpoint with mandated default `2026-08-01T00:00:00Z`; batches define business days (Mon–Fri validated), so sustained-overdraft counting is deterministic.
- Fees debit the ledger only at settle (never during their own batch's seal), breaking the fee/balance circularity with an observable intermediate state.
- Segregation of duties enforced by X-User-ID comparison (waiver creator ≠ approver; report finalizer ≠ submitter); AccountHolder-created waivers never auto-approve, which keeps the pending bands reachable for small amounts.
- CANCELLED batches free their business date (uniqueness applies to non-CANCELLED batches only) — pinned in both the validation row and error condition.

## Step 3: Copy Shared Files — 2026-08-14T10:42:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1708_overdraft_program_fee_governance/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-14T10:50:00.000Z

All audits pass. The PRD is complete and verified against the scaffold.

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1708_overdraft_program_fee_governance/workspace/PRD.md` — 299 lines (~52 KB)

**Section list:**
- §1 Introduction (2 paragraphs, regulatory-context angle)
- §2 Global Specifications: 2.1 RBAC (7 roles, identity prose per role), 2.2 API Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md` — verified identical), 2.3 Pagination, 2.4 Logical Clock & Business Dates, 2.5 Common Resource Properties (incl. `WaiverRequestItem` no-`updated_at`/no-`version` exception), 2.6 Money/Counts/Rounding, 2.7 Working vs Ledger Balance, 2.8 OCC, 2.9 Segregation of Duties, 2.10 Validation Precedence & Identifier Resolution
- §3 Business Logic (9 subsections, organized along the money's chronological path: program setup → accounts/consent → authorization → seal → settle → waivers → notices → offers → reports)
- §4 Endpoint Definitions (51 rows, 4 columns; method/path/roles verified equal to scaffold, zero diffs)
- §5 Error Code Catalogue (31 rows, 2 columns; verified identical to scaffold in content and order)

**Coverage audit (machine-checked):**
- Contract 1 (Field-Name Coverage): 77/77 entity-field names present in backticks; 40/40 endpoint input/query identifiers present (incl. `to_iso8601`, `current_utc`, `expected_program_version`, `expected_account_version`); 71/71 enum/state values present. **PASS**
- Contract 2 (Rule Coverage): 13 validation priorities expressed as an explicit ordered narrative in §2.10 (incl. overlap-before-gap within the temporal tier); both OCC rules expressed with write operation + `expected_*_version` field + exact error id + HTTP 412; all 6 calculations rendered as reconstruction-safe prose (posting order/fee test, working-vs-ledger pinning, waiver allocation with per-item round-half-up-then-sum, sustained-day counting, steering window, report metrics with floor division and the 1500-bps/1200-centi scrutiny constants); all state-machine transitions across 10 machines expressed with preconditions paired to error ids and all cascades (reversal → `VOIDED` fees + `lifetime_fees_waived_cents`; charge-off → `DENIED_FINAL`/`EXPIRED`; settle → fee posting + day counting + steering sweep); sibling branches given symmetric density (HIGH_TO_LOW vs CHRONOLOGICAL, FULL/FIXED_AMOUNT/PERCENT_BPS, 4 waiver entry bands, 3 approve/deny bands, provisional vs final revenue). **PASS**
- Contract 3 (§3 Path Purity): 574 backtick tokens scanned in §3; 0 path tokens, 0 bare HTTP methods, 0 method+path combos. **PASS**

**Zero-Silence-Rule decisions worth recording:**
1. **Recovery-credit ledger semantics** — the scaffold zeroes `ledger_balance_cents` at charge-off and defines the `charged_off_cents` + `recovered_cents` == `charge_off_original_cents` invariant, but never explicitly says whether a recovery credit touches the ledger. The PRD states recovery postings do not alter the zeroed ledger (they move `charged_off_cents`/`recovered_cents` only), the only reading consistent with the invariant and the closed-account posture.
2. **`period_end` < `period_start` error mapping** — the field constraint exists but no dedicated error id; mapped to `ERR_INVALID_REQUEST` (body well-formedness tier), the only compatible catalog entry.
3. **Supersession scope for auto-created offers** — the supersede transition is generic, but both auto-create paths require no `OFFERED` offer to exist; the PRD states supersession is in practice a manual-creation effect, reconciling the two scaffold statements without inventing a cascade.
4. **Deny at a mismatched band** — the scaffold gives band-specific deny transitions but no `ERR_WAIVER_EXCEEDS_AUTHORITY` for deny (unlike approve); the PRD treats out-of-band denial as an invalid state transition, mirroring the transition table exactly.
5. **`routing_band` vs initial status** — an `AccountHolder` request at/below the teller cap carries `routing_band` `TELLER` yet is born `PENDING_SUPERVISOR`; the PRD states the band reflects the amount alone while status also depends on creator role, per the scaffold's field description and entry transitions.

The withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were not opened, grepped, or referenced at any point.

## Step 6: Generate Implementation — 2026-08-14T11:24:00.000Z

Implementation complete and verified. Final summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1708_overdraft_program_fee_governance/workspace/implementation/`)

- `start.sh` — guarded launcher (`pip install` only when flask missing, `exec python3 app.py`, binds `0.0.0.0:$PORT` default 10000), executable
- `requirements.txt` — flask
- `app.py` — Flask entry point, blueprint registration, envelope-shaped error handlers (ApiError/404/405/400/500)
- `db.py` — in-memory dict stores (11 entity types), logical clock (default exactly `2026-08-01T00:00:00Z`), UUID minting, `created_at/updated_at/version` system fields, **no seeding of any kind — store starts empty**
- `errors.py` — ApiError + all 30 catalog error IDs
- `helpers.py` — response envelope (`meta.api_request_id/api_request_timestamp`, `response_type`, `data`; error body `error_id`/`message`), `limit/offset/total_count/has_more` pagination (default 10, clamp [1,100]), auth tier-1/tier-2, body/field/date validators
- `serializers.py` — per-entity views (fee `outstanding_cents` computed; offer status surfaced with lazy EXPIRED; WaiverRequestItem carries only `id`/`created_at`)
- `services.py` — seal sweep, settle, reversal, waiver allocation/apply, charge-off cascade, auto-offer caps, report metrics
- `routes/` — 11 blueprints: clock, programs, accounts, elections, transactions, batches, fees, waivers (+waiver-items), notices, offers, reports

## Endpoints: 50/50 implemented
All routes from scaffold §1.5 including `/v1/_clock/set_current_utc`, all CRUD/list/filter endpoints, and all action endpoints (suspend/resume, close, revoke/reinstate, reverse, seal/settle/cancel, approve/deny/escalate/appeal, issue/activate/withdraw, accept/decline, finalize/submit).

## State machines implemented
Program ACTIVE↔SUSPENDED; Account ACTIVE→RESTRICTED→(cure|CLOSED_CHARGEOFF) + ACTIVE→CLOSED_VOLUNTARY with open-items/negative-balance guards; OptInElection OPTED_IN↔REVOKED cyclic; Transaction AUTHORIZED→POSTED/RETURNED_NSF, POSTED→REVERSED (SEALED-only window); PostingBatch OPEN→SEALED→SETTLED/CANCELLED; OverdraftFee ASSESSED→POSTED/WAIVED/VOIDED (SUSTAINED born POSTED); FeeWaiverRequest band-routed entry (auto-APPLIED ≤5000 for staff only; AccountHolder always pending) + approve/deny/escalate/appeal with deny→appeal loop and terminal DENIED_FINAL; Notice DRAFT→ISSUED→EFFECTIVE + WITHDRAWN/SUPERSEDED; EducationOffer OFFERED→ACCEPTED/DECLINED/EXPIRED(lazy)/SUPERSEDED; RegulatoryReport OPEN→FINALIZED→SUBMITTED.

## Calculations / key rules
Posting-order variants (HIGH_TO_LOW vs CHRONOLOGICAL, credits first, created_at tie-breaks never id); working-vs-ledger separation (fees debit only at settle, never cascade same-batch); 4-part fee test (ACTIVE program, strict de-minimis `>`, strict count cap `<`, cent cap `<=` exact fit); per-account 1-based posting_sequence incl. NSF items; sustained day counting with `>=` thresholds, SUSTAINED fee (cap-exempt, skipped when SUSPENDED), charge-off cascade (PENDING→DENIED_FINAL, OFFERED→EXPIRED, charged_off/recovered/original invariant); steering sweep with trailing closed window and one-auto-offer-per-window caps; waiver allocation (FULL / FIXED_AMOUNT waterfall / PERCENT_BPS round-half-up **per item then sum**), band routing 5000/20000/100000, self-decision and fee-state guards before authority band (tier order), recompute-at-approve; report metrics (provisional incl. ASSESSED vs final POSTED/WAIVED-only, floor-division ratio/avg, scrutiny >1500 bps or ≥1200 centi); notice half-open `[sent_at, effective_at)` overlap; report tiling (overlap checked before gap, first report exempt); OCC `expected_program_version`/`expected_account_version` checked last (412); full 13-tier validation precedence.

## Boot verification
`bash start.sh` on a fresh process (PORT=17900): booted within 3s, `GET /v1/accounts` returned the correct envelope with `total_count: 0` (proving empty store), program create returned 201. Three smoke suites exercised the full lifecycle end-to-end — seal/settle balances, NSF returns, reversal voiding, restriction/charge-off/recovery, waiver routing/appeals, notice windows, offer expiry, report metrics, pagination — all responses matched the PRD, including error IDs and HTTP statuses (400/403/404/409/412/422).

## Step 5: Generate Unit Tests — 2026-08-14T11:45:00.000Z

Generation complete. Summary below.

## Files written

**`test_helpers/`** (9 files) under `/home/ubuntu/github/CodingPRD/tasks/task_1708_overdraft_program_fee_governance/test_helpers/`:
- `types.py` — all status/type enums + 12 entity TypedDicts (WaiverRequestItem correctly omits `updated_at`/`version` per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (46 methods, `/v1` prefix)
- `api_errors.py` — all 31 PRD §5 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions + `assert_chargeoff_invariant` / `assert_fee_net_position`
- `factories.py`, `constants.py` (standard program config, authority caps, Mon–Fri business dates), `test_users.py` (opaque role constants + `make_account_holder_headers(account_id)` for the entity-backed AccountHolder role), `fixtures.py` (~25 composite helpers: `run_posting_day`, `make_posted_fee_scenario`, `make_restricted_scenario`, `make_charged_off_scenario`, `make_issued_notice`, OCC-aware `create_notice`/`create_offer`, `submit_waiver`), `__init__.py` barrel

**`test_suite/`** — `conftest.py` + 13 numbered test files.

## Test counts

- **Queue A (Difficulty): 38 tests** — all 19 instances × 2 tests each.
- **Queue B (Corner): 55 tests** — all 54 non-stub instances covered (one instance, `steering_offer_at_exact_fee_count_threshold`, deliberately has 2 tests for below/at threshold). The 19 `excluded_because:` stubs were not translated; all stub cross-references verified to resolve to real difficulty instances.
- **Total: 93 tests**, all collected cleanly by pytest; all modules compile and import.

## Design-tag audit result

CLEAN. Every test docstring ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line; every tag resolves to a real instance in the source YAML; every difficulty instance has ≥2 tests and every non-stub corner instance ≥1. Separately, all 158 quoted PRD citation spans were mechanically verified to match `workspace/PRD.md` verbatim (whitespace-normalized); 4 initial mismatches (markdown `**` leakage, ellipses fusing sentences) were found and fixed.

## Skipped instances

None. Every non-stub instance passed the PRD-first two-condition filter.

## Design-index defects found (and how handled)

1. **`Difficulty/cross_entity_state_dependency/account_close_blocked_by_pending_waiver`** — the recipe seals the 2026-08-03 funding batch but never settles it, so the 2026-08-04 batch's settle would hit `ERR_EARLIER_BATCH_UNSETTLED` mid-fixture. The chain was minimally repaired (settle the empty-of-fees 08-03 batch; settling changes no asserted value — the instance's own annotation confirms the intent). All asserted literals kept as designed.
2. **`Corner/calculations/sustained_fee_exempt_from_daily_caps`** — the yaml asserts `ledger == -12000`, but its own parenthetical computes `-6000 - 10500 - 3000` (= −19500), and the PRD uniquely derives **−19500** (items −6000 at seal; 10500 OVERDRAFT fees debit at settle per §3.5; 3000 SUSTAINED fee debited immediately at restriction per §3.5). The test emits the PRD-derived −19500; all other asserted values (3 fees / 10500 / SUSTAINED 3000 with null `transaction_id` born POSTED / lifetime assessed 13500 / RESTRICTED) are kept verbatim.

## PRD-coverage gaps

None discovered. The PRD verbatim-covers every asserted rule, including the two validation-precedence pairs (§2.10's tier enumeration explicitly orders state-tier 7 over fiscal-tier 12 and posture-tier 8 over temporal-tier 9), both OCC rules (§2.8), and the closed-interval report tiling with overlap-before-gap ordering (§3.9).

## Step 7: Run Tests and Iterate — 2026-08-14T12:05:00.000Z

Summary

**Iterations run:** 2 (initial sweep: 5 deterministic failures in all 8 rounds; post-fix sweep: 93/93 passed in all 8 rounds).

**Tests deleted:** none. Every failing assertion traced to a verbatim PRD rule; no PRD-silent or non-uniquely-derivable test required deletion.

**Fixes applied to `test_helpers/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1708_overdraft_program_fee_governance/test_helpers/assertions.py` — added `assert_same_instant(actual, expected, label)` (exported via the package barrel). Why: PRD §2.4/§3 pin the *instant values* of `sent_at`/`effective_at`/`expires_at` (clock-derived, day arithmetic), but no PRD sentence pins their string rendering — §2.5's three-fractional-digit format is stated only for `created_at`. Exact-string equality against a no-fractional-digit literal failed the two-reader test (the implementation's `.000Z` rendering is equally PRD-conformant), so assertions now compare parsed instants. This is a STEP 1c split: the covered arithmetic assertion kept, the uncovered format assertion removed.

**Fixes applied to `test_suite/` (test-artifact side of the same correction):**
- `test_07_steering_offers.py` — `TestOfferAcceptAfterExpiryRejected`: `expires_at` assertion switched to `assert_same_instant`.
- `test_10_change_notices.py` — five assertion sites across `TestNoticeWindowsHalfOpenAdjacency` (both tests) and `TestNoticeActivateSuspendedBeatsWindowError::test_failed_activation_applies_nothing` switched to `assert_same_instant`. All window/overlap/expiry *behavior* assertions (error IDs, statuses, version bumps) left untouched.
- `test_02_posting_order_fee_assessment.py` — `_cap_de_minimis_scenario()` fixture: funding batch now uses `settle=True` instead of `settle=False`. Why: the fixture left the Monday funding batch `SEALED`, so the test that settles the Tuesday batch was correctly rejected with `ERR_EARLIER_BATCH_UNSETTLED` (PRD §3.5 verbatim: settle requires every earlier-dated batch `SETTLED` or `CANCELLED`). The fixture violated the PRD precondition — a STEP 2 test bug, not an implementation bug. Asserted values are unchanged (the settled empty-of-fees funding day resets no counter and posts no fee).

**Fixes applied to `implementation/`:** none. All five failures were test-side; the implementation's behavior (timestamp rendering with three fractional digits, earlier-batch settle gating) was already PRD-faithful.

**Final state:** 8/8 parallel rounds × 93/93 tests passed, zero failures, zero errors.

## Step 8: Finalize PRD — 2026-08-14T12:20:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1708_overdraft_program_fee_governance/workspace/PRD_FINALIZED.md` produced with exactly one minimal insert; everything else verbatim.

**Line counts / delta:** PRD.md 299 lines → PRD_FINALIZED.md 301 lines (+2 lines: the new sentence + its separating blank line; +0.67%).

**Changes (one total):**
- §2.5 — insert — added one sentence after the `version` bullet pinning that every system-generated timestamp string the API serves (including `updated_at`, the clock-derived instants of §2.4 `elected_at`/`last_changed_at`/`sent_at`/`effective_at`/`expires_at`, and the clock endpoint's `current_utc` echo) is rendered ISO 8601 UTC with exactly three fractional digits, whole-second instants carrying `.000` (e.g. `2026-08-01T00:00:00.000Z`) — impl: `db.py:53-56` (`fmt_ts`, the sole renderer), callsites `db.py:59-60,78-79,89,95`, `election_routes.py:49-50,87,115`, `notice_routes.py:129-130`, `offer_routes.py:54`, `services.py:163`, `helpers.py:32`, `clock_routes.py:23`+`db.py:40-42`.

**Step 7 items disposition:**
- `assert_same_instant` (test_helpers + 6 testsuite sites) — genuine PRD silence → the one §2.5 edit above.
- `settle=True` fixture fix in `test_02` — pure fixture bug: PRD §3.5 (line 155) already pins earlier-batch settle gating verbatim ("only once every earlier-dated batch of the same program has reached `SETTLED` or `CANCELLED` ... rejected with `ERR_EARLIER_BATCH_UNSETTLED`"). Confirmed against impl `batch_routes` settle path; no PRD edit.

**Pre-edit search log (mandatory, for the single edit):**
- (a) Subject: string rendering format of all system-generated timestamp fields (clock-derived instants, `updated_at`, `current_utc` echo) — the fields Step 7's `assert_same_instant` showed unpinned.
- (b) Impl paths enumerated and read/grepped: full-repo grep for `now_iso|fmt_ts|clock_raw|elected_at|last_changed_at|sent_at|effective_at|expires_at` over all `*.py`; read `db.py` (fmt_ts/now_iso/clock raw handling), `serializers.py` (all entities — pass-through, no re-rendering; exhaustive timestamp-field inventory), `helpers.py:32` (envelope `api_request_timestamp`), `clock_routes.py` (echo only ever served post-set via `fmt_ts`; startup raw never observable), `notice_routes.py:118-130,147,169`, `offer_routes.py:54`, `services.py:163`, `election_routes.py:49-50,87,115`. Date-valued fields (`authorized_date`, `posted_date`, `business_date`, `period_start/end`) verified as `YYYY-MM-DD` strings, already PRD-pinned, out of scope.
- (c) Wording adjustments: (1) chose a universal claim ("every system-generated timestamp string the API serves") over an exhaustive enumeration because the grep confirmed every extant path uses the same `fmt_ts` renderer — universal is exactly true and can't misdescribe any path; (2) used "including" so the list is non-exhaustive and doesn't implicitly exclude `api_request_timestamp` (already pinned in §2.2, left verbatim); (3) scoped the claim to *rendering/serving* only, leaving input parsing (`parse_ts`, which accepts non-fractional forms) unpinned, matching §2.4's existing silence; (4) included `.000` example so a fresh implementer reproduces the zero-padding the tests tripped on.

## Step 9: Complete PRD — 2026-08-14T12:35:00.000Z

All changes are in place: 20 single-line, in-paragraph edits; no sections added or removed. Final verification is complete.

## Summary

**Source vs output:** `/home/ubuntu/github/CodingPRD/tasks/task_1708_overdraft_program_fee_governance/workspace/PRD_FINALIZED.md` (301 lines, 52,740 chars) → `/home/ubuntu/github/CodingPRD/tasks/task_1708_overdraft_program_fee_governance/workspace/PRD_COMPLETED.md` (301 lines, 55,467 chars). Char delta: **+2,727**. Line count unchanged — every change is an inline insert/revision within an existing paragraph; no new sections.

**Counts:** 20 changes total — **ambiguity-pins: 20, mismatch-revisions: 0**. Every behavior the PRD already pinned (posting orders, fee-test thresholds, caps, rounding, routing bands, precedence tiers, state machines, error codes, endpoint roles) matched the implementation exactly; all edits pin behavior where the PRD prose was silent or admitted multiple readings. (14 pure inserts, 6 in-place revisions of existing wording.)

**Changes (section — insert|revise — ambiguity — what changed — impl ref):**

- §2.1 — revise — ambiguity — header rejection extended from "empty value" to "empty or whitespace-only value" (impl strips both headers) — `implementation/helpers.py:60-64`
- §2.3 — insert — ambiguity — out-of-range `limit`/`offset` are clamped to the nearest bound (not rejected); non-integer values rejected with `ERR_INVALID_REQUEST` — `implementation/helpers.py:127-141`
- §2.3 — insert — ambiguity — list sort ties (identical `created_at`, common under the logical clock) keep relative creation order — `implementation/helpers.py:153-155`
- §2.5 — revise — ambiguity — `version` pinned to begin at 1 for every resource (previously pinned only for programs in §3.1) — `implementation/db.py:74-84`
- §3.1 — insert — ambiguity — all eleven numeric program parameters must be integers; the ten besides `fee_amount_cents` accept zero — `implementation/routes/program_routes.py:26-41`
- §3.2 — revise — ambiguity — the charge-off triple (`charge_off_original_cents`, `charged_off_cents`, `recovered_cents`) is zero-initialized at opening and present from birth, not merely "after a charge-off" — `implementation/routes/account_routes.py:42-44`, `implementation/serializers.py:47-49`
- §3.2 — insert — ambiguity — election creation is refused on a closed account (`ERR_ACCOUNT_CLOSED`), permitted on `RESTRICTED`; both `elected_at` and `last_changed_at` are stamped at creation — `implementation/routes/election_routes.py:35-36,49-50`
- §3.2 — insert — ambiguity — reinstatement also stores the presented `disclosure_version` on the election — `implementation/routes/election_routes.py:113-115`
- §3.2 — insert — ambiguity — voluntary close runs the negative-balance check before the open-items scan (both-failing accounts surface `ERR_CLOSE_NEGATIVE_BALANCE`) — `implementation/routes/account_routes.py:80-93`
- §3.4 — insert — ambiguity — the seal sweep is not gated by account posture (a still-`AUTHORIZED` item posts/returns even if the account became `RESTRICTED` or closed since authorization), and an itemless batch seals normally with counters at zero — `implementation/services.py:52-61`
- §3.4 — revise — ambiguity — reversal adds each voided fee's *remaining outstanding* amount (`amount_cents` minus already-waived cents) to `lifetime_fees_waived_cents`, not the full face amount — `implementation/services.py:278-283`
- §3.5 — insert — ambiguity — the charge-off cascade's forced `DENIED_FINAL` records no `denied_band` and no `decided_by_user_id` — `implementation/services.py:176-180`
- §3.6 — insert — ambiguity — waiver submission posture: permitted on `ACTIVE`/`RESTRICTED`, rejected on closed with `ERR_ACCOUNT_CLOSED`; duplicate `fee_ids` entries are permitted (each entry validated and given its own item row, the FIXED_AMOUNT bound sums per listed entry, but the allocation walk visits each distinct fee once) — `implementation/routes/waiver_routes.py:41-80,109-115`, `implementation/services.py:293-312`
- §3.6 — insert — ambiguity — auto-approved (staff, ≤ teller cap) requests also get `WaiverRequestItem` rows, written with applied `waived_cents`, and keep `decided_by_user_id` null — `implementation/routes/waiver_routes.py:109-117`, `implementation/services.py:349-350`
- §3.6 — insert — ambiguity — approval check order pinned: pending-state validity → self-decision guard → fee-state revalidation (`ERR_FEE_STATE_CHANGED`) → band-authority — `implementation/routes/waiver_routes.py:142-159`
- §3.6 — insert — ambiguity — denial runs the same checks in the same order except the fee-state revalidation, which is approval-only — `implementation/routes/waiver_routes.py:174-191`
- §3.6 — insert — ambiguity — escalation and appeal carry no self-decision guard and no account-posture gate; appeal preserves the recorded `denied_band`/`decided_by_user_id` until a later decision overwrites `decided_by_user_id` — `implementation/routes/waiver_routes.py:194-230`
- §3.7 — insert — ambiguity — a `new_value` failing the string shape (non-enum for `POSTING_ORDER`, non-integer otherwise) is rejected with `ERR_INVALID_REQUEST`, with no range check beyond integer parseability — `implementation/routes/notice_routes.py:44-53`
- §3.8 — insert — ambiguity — manual offer creation is refused on a closed account (`ERR_ACCOUNT_CLOSED`); `RESTRICTED` accounts accept manual offers — `implementation/routes/offer_routes.py:36-37`
- §3.9 — revise — ambiguity — report metrics are scoped to fees of the report's program (via the fee's batch), not "all fees" system-wide — `implementation/services.py:367-372`

**Deliberately not pinned** (out of PRD scope / unobservable): infrastructure error handlers (unknown path → 404 `ERR_NOT_FOUND`, `ERR_INTERNAL` 500 catch-all in `app.py:32-49`), lenient ISO parsing details in `db.py:63-67`, and internal sequencing tie-breaks that cannot affect any response (account processing order during seal/settle is per-account independent; fee-debit order at settle sums identically).
