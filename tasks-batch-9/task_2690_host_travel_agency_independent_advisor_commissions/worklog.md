## Step 1: Create task directory — 2026-09-04T07:08:49.253Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2690_host_travel_agency_independent_advisor_commissions and its workspace/ subdirectory. Index 2690 pre-assigned by the orchestrating prompt (no scan/allocation performed).

## Step 2: Generate scaffold — 2026-09-04T08:46:54.391317186Z

All three artifacts are complete and the linter is green.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5
```

Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_2690_host_travel_agency_independent_advisor_commissions/`):

| file | lines | bytes |
|---|---|---|
| `SCAFFOLD.yaml` | 2817 | 147,925 |
| `SCAFFOLD_DIFFICULTY_DESIGN.yaml` | 2296 | 160,344 |
| `SCAFFOLD_CORNER_DESIGN.yaml` | 3809 | 258,216 |

SCAFFOLD.yaml (§1.0–§1.7 only; no design keys present)
- `difficulty_level: expert_plus`; archetypes `ledger_reconciliation` / `compliance_audit`; topology `flat`; state-machine shape `parallel`; role model `segregation_of_duties`; consistency `immediate`; complexity layers: dual_variant_calculation, cascading_side_effects, rate_threshold_triggers, optimistic_concurrency, derived_field_reconciliation.
- 12 entities, 8 state machines (Advisor, Booking ×2 parallel dimensions — booking_status and commission_status, CommissionClaim, ComplianceCredential, AdvisorAgreement, SettlementRun, AdvisorStatement), 2 §1.2.1 concurrency rules (advisor agreement create, client trust-ledger append), 11 calculations, 30 ordered validations, 47 endpoints, 52 errors, 5 roles.

SCAFFOLD_DIFFICULTY_DESIGN.yaml — 9 rules / 19 instances (≥2 each)
dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 2, priority_pair_validation_conflict 2, boundary_precision_check 2, cross_entity_state_dependency 2, resource_temporal_overlap 2, compensating_invariant 2.

SCAFFOLD_CORNER_DESIGN.yaml — all 9 taxonomy sections, 61 instances (47 with `test_recipe`, 14 `excluded_because` stubs)
entities 12, state_machines 10 (7+3), calculations 8 (4+4), validations 10 (7+3), endpoints 5 (4+1), errors 5, rbac 4, cross-cutting complexity layers 6 (3+3: both OCC stale-version corners plus supplier-aging derived-field reconciliation), consistency model 1.

Verification performed
- 1039 §1.8+§1.9 call objects lint-clean against §1.5 (endpoint declared, role legal, payload ⊆ inputs, captures resolve to declared output fields), FK reverse-reachability satisfied.
- All 80 instance names unique across the two design files.
- All 52 §1.6 error ids are referenced by at least one design instance (0 unreferenced) — this required adding validation priority 38 (`ERR_RUN_NOT_POSTED`) and re-scoping priority 92 in SCAFFOLD.yaml, since a POSTED statement always implies a POSTED run and the id was otherwise structurally unreachable.
- Money/date literals were hand-derived from the declared formulas; three stale supplier-aging asserts were corrected to honor the cohort filter `due_date = travel_end_date + Supplier.remit_terms_days <= as_of_date`.
- No sibling `task_*/` directory was read, listed, or grepped at any point.

## Step 3: Copy shared files — 2026-09-04T08:46:54.409518382Z

Copied ./INSTRUCTION.md to workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-09-04T09:00:00.163949929Z

PRD generated at `workspace/PRD.md`.

**Size and shape:** 406 lines / 94,268 characters. Final heading is `## 5. Error Code Catalogue`; the file ends at the last error-table row (`| \`ERR_CLOCK_REWIND_FORBIDDEN\` | 422 |`) with a trailing newline — tail verified intact, no mid-sentence truncation.

**Sections covered:**
- §1 Introduction (3 paragraphs: business context, the two failure modes the system exists to kill, scope)
- §2 with 12 subsections: 2.1 Actors/Headers/RBAC, 2.2 API Response Structure, 2.3 Pagination and List Ordering, 2.4 Common Resource Properties, 2.5 The Logical Clock, 2.6 Money/Rounding/Round-Then-Sum, 2.7 Version Pinning and OCC, 2.8 Path Resolution and Rejection Ordering (the full 16-band ordered validation chain), 2.9 Cascade Discipline and Derived-Field Reconciliation (both conserved quantities), 2.10 Dual-Basis Production Accounting, 2.11 Segregation of Duties, 2.12 Seller-of-Travel Regimes and Trust Obligations
- §3 with 9 domain subsections: reference data → advisor onboarding/agreements/activation → credentials → clients and trust → booking submission and pricing → fulfilment/cancellation (chargeback cascade) → remittance/aging/claims → monthly settlement → departure cascade
- §4 47-endpoint table, §5 52-error table

**Counts documented:** 12 entities / 117 entity field names / 72 endpoint input+query identifiers / 47 endpoints / 52 error codes / 30 ordered validations / 11 calculations (all variants) / 37 state transitions across 8 state machines / 2 OCC rules / 2 four-link cascades.

Hard Contract reports: field coverage PASS (117/117 fields, 72/72 inputs, 30/30 states, 60/60 enum values, 5/5 roles, 52/52 errors narrated in §2/§3 not only §5); rule coverage PASS (30/30 validations with explicit relative ordering, 2/2 OCC rules, 37/37 transitions, 11/11 calculations with pinned evaluation order and embedded constants, 47/47 endpoint side-effect sets, 8/8 sibling-branch symmetry groups equal density); path purity PASS (883 backtick tokens scanned in §3, 0 URL paths, 0 bare HTTP methods).

**One scaffold contradiction the generator had to resolve** (flagged for downstream steps): `Client.ownership_mode` is declared `default: HOST_OWNED` in the §1.1 entity table but the `POST /host-agency/clients` side-effect line says it defaults to `ADVISOR_OWNED`. The PRD states **`HOST_OWNED`**, following the entity field-level declaration (the source the doc-generator skill names authoritative for defaults). If §1.9's test recipes were derived from the endpoint side-effect line instead, that assertion will disagree; Step 7's STEP 1/STEP 2 protocol resolves it in the PRD's favour.

Orchestrator verification: `wc -l` 406, error-table rows 52 = scaffold's 52 `errors[].id`, no `expert`/`harder than` difficulty-instruction leakage anywhere in PRD.md, tail ends at a complete table row.

## Step 6: Generate implementation — 2026-09-04T09:29:56.670256583Z

Implementation complete and verified.

## Location
`workspace/implementation/`

## Modules (2,929 lines total)

| File | Lines | Role |
|---|---|---|
| `calc.py` | 441 | pricing, tier selection, production accounting, waterfall, aging, chargebacks, balances |
| `routes_settlement.py` | 333 | run open/calculate/post, statement read/pay |
| `routes_booking.py` | 324 | submit, confirm, traveled, cancel + CASCADE-A, commission receipt |
| `routes_advisor.py` | 315 | advisors, agreements, activate/suspend/reinstate, departure + CASCADE-B |
| `routes_reference.py` | 250 | logical clock, split schedules, consortiums, suppliers |
| `guards.py` | 242 | auth/RBAC, body whitelisting, typed field validators, pagination |
| `routes_claim.py` | 191 | file/deny/resubmit/resolve claims |
| `routes_credential.py` | 170 | credential create + VERIFY/REVOKE decisions |
| `store.py` | 153 | in-memory dicts, clock helpers, row/serialization helpers |
| `routes_client.py` | 148 | clients + append-only trust ledger |
| `errors.py` | 128 | `ApiError` + all 52 error IDs to HTTP status map |
| `app.py` | 67 | app factory, blueprint registration under `/host-agency`, error handlers |
| `lookup.py` | 62 | FK resolution with the correct 404 per entity |
| `envelope.py` | 60 | meta/data envelope, list meta, error body |
| `listing.py` | 34 | filter + order + paginate + serialize |
| `start.sh` | 10 | guarded `pip install`, `exec python3 app.py` on `$PORT` |
| `requirements.txt` | 1 | `Flask==3.0.3` |

## Coverage
- **47 endpoints** (exactly matching SCAFFOLD.yaml), all under `/host-agency`, `strict_slashes = False`.
- **12 entities**, in-memory dicts only, **zero seeding** — a fresh boot returns `total_count: 0` on every collection.
- **8 state machines**: Advisor (cyclic ACTIVE<->SUSPENDED, terminal DEPARTED), Booking `booking_status` and `commission_status` as parallel axes, ComplianceCredential, CommissionClaim (cyclic SUBMITTED->DENIED->SUBMITTED, capped at 3 rounds), AdvisorAgreement, SettlementRun (compound CLOSED bubbled up from statements), AdvisorStatement.
- **11 calculations**: booking pricing (4 pinned steps incl. INTERNAL_TOOL bonus, consortium bonus, rate ceiling, per-booking cap), dual-basis production (PROVISIONAL vs FINAL) with tier resolution, round-then-sum settlement shares, platform-fee waterfall (fee tier on PRE-fee gross share, marketing fund on POST-fee base), chargeback GROSS_REVERSAL vs NET_OF_RETENTION, carryforward (replaced, not accumulated), supplier 4-bucket aging, claim aging/escalation, trust running balance, advisor lifetime totals, consortium marketing fund.
- **29 validations** from the scaffold, ordered per the PRD's 16-band rejection ordering; OCC via `expected_advisor_version` / `expected_client_version` (412); segregation of duties on run post; rejected requests leave no trace (booking submit and run calculate both use plan-then-commit / snapshot-rollback).
- Both 4-link cascades implemented and exercised.

## Smoke test (fresh `PORT=... bash start.sh`, killed by exact port-derived PID)
Full happy path plus edges, all returning PRD-exact values:
- pricing `0.17 x 800000 base = 136000`; INTERNAL_TOOL `0.16 + 0.005 = 0.165`
- settlement: gross `182500` -> share `127750` (round-then-sum) -> fee 5% of pre-fee `127750 = 6388` -> marketing 2% of `121362 = 2427` -> net `118935`
- CASCADE-A: cancel of a settled CONFIRMED/RECEIVED booking -> `CHARGED_BACK`, chargeback `70000 x (1 - 0.10) = 63000` -> supplier hit threshold 2 -> `PROBATION` -> PENDING bookings repriced -> provisional recomputed; next run absorbed it (share 0, net 0, carryforward `63000`), `chargeback_recognized_at` stamped at calculation
- CASCADE-B: departure finalize -> `DEPARTED` -> agreement `TERMINATED` -> HOST_OWNED client re-homed to successor / ADVISOR_OWNED client `RELEASED` -> in-flight booking followed the client and was repriced -> both advisors' provisional recomputed; `ERR_DEPARTURE_BLOCKED` correctly raised while trust funds remained
- claim cycle SUBMITTED->DENIED->SUBMITTED(round 2)->RESOLVED_PAID; run POSTED->CLOSED after the last statement was PAID
- error paths confirmed: `ERR_CLOCK_REWIND_FORBIDDEN`, `ERR_ADVISOR_VERSION_STALE`, `ERR_CREDENTIAL_COVERAGE_OVERLAP`, `ERR_SEGREGATION_OF_DUTIES`, `ERR_TRANSITION_ADVISOR_INVALID`, `ERR_INVALID_ADVISOR_STATE`, `ERR_ADVISOR_NOT_ACTIVE`, `ERR_SETTLEMENT_PERIOD_DUPLICATE`, `ERR_ADVISOR_EMAIL_DUPLICATE`, `ERR_UNAUTHENTICATED` (401), unknown-field/`limit=0` -> `ERR_INVALID_REQUEST`

All 15 `.py` files pass `python3 -m py_compile`; `__pycache__/` removed; no smoke process left listening (verified ports 51873 and 51907 free), and no broad `pkill` was ever used. The test suite, test helpers and design YAMLs were never read.

## Step 5: Generate unit tests — 2026-09-04T10:20:15.933062946Z

Both remaining queue-B modules are written and the full verification sweep is green.

## Deliverables

**`test_helpers/`** (Stage 1 — 2,393 lines total)
`__init__.py` 43 · `api_client.py` 266 · `api_errors.py` 118 · `assertions.py` 371 · `constants.py` 49 · `factories.py` 304 · `fixtures.py` 786 · `test_users.py` 68 · `types.py` 388

**`test_suite/`** (Stage 2 — 5,815 lines total, 85 tests)

| file | lines | tests |
|---|---|---|
| `conftest.py` | 53 | — |
| `test_chargeback_and_departure_cascades.py` | 314 | 4 |
| `test_claim_cycle_and_advisor_cycle.py` | 224 | 4 |
| `test_commission_rate_selection_matrix.py` | 161 | 3 |
| `test_conservation_invariants.py` | 317 | 4 |
| `test_cross_entity_gates.py` | 257 | 4 |
| `test_dual_basis_and_chargeback_variants.py` | 289 | 4 |
| `test_rejection_priority_pairs.py` | 220 | 4 |
| `test_settlement_rollup_and_fee_waterfall.py` | 236 | 4 |
| `test_temporal_overlap_intervals.py` | 260 | 4 |
| `test_tier_and_aging_boundaries.py` | 218 | 4 |
| `test_corner_entities.py` | 531 | 12 |
| `test_corner_state_machines.py` | 486 | 7 |
| `test_corner_calculations.py` | 250 | 4 |
| `test_corner_validations.py` | 546 | 7 |
| `test_corner_endpoints.py` | 314 | 4 |
| `test_corner_errors.py` | 406 | 4 |
| `test_corner_rbac.py` | 308 | 4 |
| `test_corner_complexity_layers.py` | 306 | 3 |
| `test_corner_consistency.py` | 119 | 1 |

## Coverage per queue

- **Queue A (Difficulty, §1.8): 39 tests** over all **19** non-stub instances — every instance has >=2 tests; `expected_commission_mode_a_rate_selection_matrix` has 3.
- **Queue B (Corner, §1.9): 46 tests** over **46 of 47** non-stub instances (target >=1 each). 14 further instances carry `excluded_because` and were correctly not translated.

## Skipped design instances

- `Corner/errors/corner_split_schedule_with_no_zero_tier_is_a_configuration_error` — **non-unique-derivability**: PRD §3.1 makes "exactly one entry must sit at a `min_production_cents` of 0" a creation-time constraint, while §3.5 raises `ERR_SPLIT_TIER_UNRESOLVED` for "a misconfigured ladder with no zero floor" at submission; the PRD does not pin which endpoint rejects, so no single outcome is derivable.

That is the only skip. The same unreachable trigger was also dropped from `corner_enum_and_range_type_constraints_rejected`, which was still translated through its two enum-member violations.

## Verification results

- `python3 -m py_compile` on all 9 `test_helpers/*.py` and all 20 `test_suite/*.py` — **OK**, no failures.
- **Import resolution**: every name imported from `test_helpers` resolves against the actually-imported package — 0 missing.
- **Unused imports**: 0 across all 20 suite modules (AST checker).
- **Design-tag pass**: exactly one `Design:` line per test, always the docstring's last line; 0 dual-tagged; every tag resolves to a real non-stub instance in the source yaml; 0 tags pointing outside the non-stub sets.
- **PRD-citation pass**: all 93 quoted sentences in test docstrings are whitespace-normalized verbatim matches in `workspace/PRD.md`. One miss was found and fixed (`test_a_fully_paid_booking_can_claim_no_amount_at_all` was paraphrasing §3.7; replaced with the actual "From `commission_status` `RECEIVED`, the booking's `shortfall_cents` must be strictly greater than zero..." sentence). The supplier-reconciliation docstring was likewise corrected to the real §3.7 aging-cohort sentence.
- **Scaffold-citation pass**: 0 occurrences of "scaffold" in any emitted code.
- No `skip`/`xfail`/`TODO`/`FIXME` placeholders anywhere.
- **Location check**: `find` confirms `test_helpers/` and `test_suite/` exist only at the task root; `workspace/` contains only `INSTRUCTION.md`, `PRD.md` and `implementation/` (never read, never written). `__pycache__` artifacts from the compile check were removed.

## Notes on the two new modules

`test_corner_complexity_layers.py` grounds both optimistic-concurrency tests on the verbatim PRD §2.7 sentences (`ERR_ADVISOR_VERSION_STALE` 412 "and no agreement row is written"; `ERR_CLIENT_VERSION_STALE` 412 "and nothing is appended") and asserts the no-effect half explicitly. The reconciliation test walks the receivable through confirm -> cancel -> receipt -> claim -> resolve with a 2026-06-10 travel end and 30-day terms so the cohort age is 22 days at the default clock, keeping every assertion in `aging_0_30_cents`.

`test_corner_consistency.py` uses a CA (trust-regime) advisor so the `CLIENT_TRUST` booking is the legal payment method, and pins that the 201 create response already carries `expected_commission_cents` and `applied_commission_rate`, that submission has already moved `production_ytd_provisional_cents` (PRD §3.5 line 229), and that the confirmation sweep's ledger line carries `booking_id` and `recorded_by_user_id` with the balance visible on the very next read.

Orchestrator verification: 85 test functions = 85 `Design:` tags; `test_helpers/` and `test_suite/` are at the task root only, nothing stray under `workspace/`; stale `workspace/implementation/__pycache__` removed before the sweep.

## Step 8 — test/fix iteration loop

Two iterations. Iteration 1 baseline: 81/85 in all 8 parallel rounds, with the
identical 4 failures in every round (no flakiness). Iteration 2: **85/85 in all
8 rounds**, confirmed by a second independent 8-round sweep (85/85 × 8 again,
153s per round).

No tests deleted. No implementation changes. All four failures were test-layer
defects in `test_suite/`:

| file | fix | why |
|---|---|---|
| `test_corner_entities.py` | added `controller` to the `test_helpers` import list | `test_trust_ledger_lines_are_append_only_and_carry_no_version` called `controller("ctrl-1")` without importing it — `NameError` before any request was issued. |
| `test_rejection_priority_pairs.py` | `_submission_attempt` now merges its defaults into a dict before splatting into `create_booking_payload` | the helper passed `payment_method=` positionally-by-keyword *and* re-passed it through `**overrides`, so both trust-regime priority tests died with `TypeError: got multiple values for keyword argument 'payment_method'`. |
| `test_corner_errors.py` | in `test_the_four_authorization_failures_are_reported_apart`, the ownership probe now submits `advisor_id=first["id"]` under `make_advisor_headers(second["id"])` | the probe previously sent `advisor_id=second["id"]` under `second`'s own headers and merely named a client owned by `first`. PRD §2.1 states verbatim that "a `Booking` is owned when its `advisor_id` equals `X-User-ID`" — so that request was *not* an ownership violation and the PRD-faithful implementation correctly returned 201. PRD nowhere requires the referenced `Client` to be owned by the submitting advisor, so adding such a check to `implementation/` would have been an untraceable capability. The fix makes the request express the ownership rule the PRD actually states. |

`workspace/implementation/` was not modified during Step 8.

## Step 7: Run tests and iterate — 2026-09-04T10:44:01.603534688Z

(Orchestrator note: the entry immediately above, headed "Step 8 — test/fix iteration loop", was appended by the Step 7 fix subagent itself and is mislabelled — it is a duplicate of this Step 7 record. The real Step 8 is the PRD finalizer, recorded below this entry. Worklog is append-only, so the mislabelled heading is left in place rather than rewritten.)

Verbatim subagent summary:

All 8 rounds green, confirmed twice.

## Summary

**Iterations run:** 2 (plus a third confirmation sweep).

- Iteration 1 baseline: **81/85 in all 8 parallel rounds**, with the *identical* 4 failures in every round — no flakiness, so all four were real defects.
- Iteration 2: **85/85 in all 8 rounds**.
- Confirmation sweep: **85/85 in all 8 rounds** again (153 s per round, 8 concurrent).

**Tests deleted:** none. All four failures survived STEP 1a/1b (PRD verbatim-covers and uniquely determines each asserted rule), so every failure resolved at STEP 2.

**Fixes applied to `test_helpers/`:** none. The fixtures and factories audited clean — every money field is already an integer, `created_at` is stamped from the logical clock so the `received_on >= created_at` fixtures line up, and the role-header builders match PRD §2.1's role-to-resource ownership model.

**Fixes applied to `implementation/`:** none. `workspace/implementation/` is byte-unchanged.

**Fixes applied to `test_suite/`** (all three were test-layer defects):

1. `test_suite/test_corner_entities.py` — added `controller` to the `test_helpers` import list. `test_trust_ledger_lines_are_append_only_and_carry_no_version` called `controller("ctrl-1")` without importing it and died with `NameError` before issuing a single request.

2. `test_suite/test_rejection_priority_pairs.py` — `_submission_attempt` now merges its defaults into a dict before splatting into `create_booking_payload`. It previously passed `payment_method=` explicitly *and* re-passed it via `**overrides`, killing both trust-regime priority tests with `TypeError: create_booking_payload() got multiple values for keyword argument 'payment_method'`.

3. `test_suite/test_corner_errors.py` — in `test_the_four_authorization_failures_are_reported_apart`, the ownership probe now sends `advisor_id=first["id"]` under `make_advisor_headers(second["id"])`.

**Key finding on #3** (the only interpretation call): the probe previously sent `advisor_id=second["id"]` under `second`'s own headers, and its only irregularity was naming a client owned by `first`. PRD §2.1 states verbatim that "a `Booking` is owned when its `advisor_id` equals `X-User-ID`" — so that request was *not* an ownership violation, and the PRD-faithful implementation correctly returned 201 (I reproduced this against a standalone server before touching anything). PRD nowhere requires the referenced `Client` to be owned by the submitting advisor, so adding that check to `implementation/` would have been an endpoint capability with no verbatim PRD trace. The fix makes the request express the ownership rule the PRD actually states, which is strictly more faithful. The test's other three probes (missing header -> 401, unrecognized role -> 401, wrong role -> `ERR_UNAUTHORIZED`, plus advisor-`REFUND` -> `ERR_TRUST_DIRECTION_FORBIDDEN`) were already correct and were left intact.

Also cleaned up `__pycache__` directories and logged the iteration in `worklog.md`. No stray `test_*` or `worklog.md` under `workspace/`.

Orchestrator verification: results.1..8.json all report `passed == total == 85`.

## Step 8: Finalize PRD — 2026-09-04T10:52:08.98901476Z

Step 8 was NOT skipped: the skip condition requires 0 deletions AND 0 `test_suite/` fixes AND 0 `test_helpers/` fixes AND 0 `implementation/` fixes, and Step 7 applied 3 `test_suite/` fixes. Verbatim subagent summary:

Done. The correct minimal patch here is very small — a single clause on one line.

## Line counts
- `PRD.md`: 406 lines; `PRD_FINALIZED.md`: 406 lines. 1 line revised, 0 added/removed -> **0% line delta**, 1/406 lines touched (0.25%).

## Changes
- **§3.5 (Booking Submission and Commission Pricing), line 213** — *revise* — the opening sentence "Only an advisor submits a booking, and only for itself." now states that the §2.8 band-5 ownership check at submission compares the submitted `advisor_id` to `X-User-ID` and consults no other reference, so a `client_id` whose `owner_advisor_id` is a different advisor is not by itself an ownership violation and the submission proceeds to the remaining gates — `implementation/routes_booking.py:52-53`.

## Per-edit pre-edit search log

**Edit 1 — §3.5 line 213**
- **(a) Subject identified:** which references `POST /bookings` ownership-checks at submission — specifically whether the referenced `Client` must be owned by the submitting advisor, and more generally whether body foreign keys other than the advisor-bearing one are ownership-checked.
- **(b) Impl paths enumerated (grepped `ERR_OWNERSHIP_VIOLATION` and `owner_advisor_id` across all of `implementation/`, then read each site):**
  - `routes_booking.py:52` (`POST /bookings`) — compares resolved `advisor["id"]` to `caller.user_id` only; `client_id` and `supplier_id` are resolved for existence (`:48-50`) and never ownership-checked. This is the Step 7 site.
  - `routes_booking.py:164` (`confirm`) — booking `supplier_id`; `:264` (`cancel`) — booking `advisor_id`, advisor-role only; `:302` (`commission-receipt`) — booking `supplier_id`.
  - `routes_claim.py:27` (file claim) — booking `advisor_id`; `:109` (deny) — referenced booking's `supplier_id`; `:129` (resubmit) — claim `advisor_id`.
  - `routes_client.py:34` (`POST /clients`) — body `owner_advisor_id` vs caller, advisor-role only; `:112` (trust-ledger append) — path client's `owner_advisor_id`, while a body `booking_id` is resolved at `:109-110` but never ownership-checked.
  - `routes_advisor.py:227-229` (`POST /advisors/{id}/departure`) — path advisor only; the body's `transition_advisor_id` is not ownership-checked.
  - `routes_advisor.py:259, 286` — the departure cascade's own reads/writes of `owner_advisor_id` (re-homing), unrelated to any submission-time check but confirmed not to imply one.
  - `guards.py:36-44` + `Caller.is_advisor` — the single authenticate/role gate feeding all of the above.
  - Cross-checked the PRD statements the wording leans on: §2.1 (ownership mapping), §2.8 band 4/5 (existence before ownership, body FKs resolved in field order).
- **(c) Wording adjustment made:** two. First, dropped an earlier draft that stated a *global* rule ("only one ownership comparison per endpoint; other body foreign keys are existence-resolved only") — it happens to be true of every path above, but it is a false-universal risk over paths Step 7 never exercised, so it was re-scoped to booking submission alone. Second, changed "...is accepted" to "...is not **by itself** an ownership violation and the submission goes on to the gates below", so the sentence cannot be read as promising a 201 — the foreign-client submission still faces `ERR_ADVISOR_NOT_ACTIVE`, the compliance gates, the trust-regime check, accreditation, and `ERR_TRAVEL_WINDOW_CONFLICT` (evaluated against *that* client's calendar and capacity, `routes_booking.py:73-83`).

## Items deliberately left unpatched
- **Step 7 items 1 and 2** carry no PRD content: item 1 was a missing `controller` import (`NameError` before any request was issued) and item 2 was a duplicate `payment_method` kwarg (`TypeError` in the test's own payload builder). Neither reveals PRD silence or mismatch, so neither earns an edit.
- No `implementation/` changes were made in Step 7 (it is byte-unchanged) and no tests were deleted, so there is no other divergence signal to trace. In particular, item 3 was resolved by making the *test* express the ownership rule the PRD already states verbatim, not by adding a client-ownership check to the implementation — so the only thing needing pinning was the negative fact that no such check exists.

Orchestrator verification: `diff PRD.md PRD_FINALIZED.md` shows exactly one changed line (213c213); both files are 406 lines; PRD_FINALIZED.md tail ends at the complete error catalogue table.

## Step 9: Complete PRD — 2026-09-04T11:15:12.403922572Z

Run as three sequential module-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (pass 1 did the `cp` from PRD_FINALIZED.md; passes 2 and 3 were forbidden to `cp` and edited in place). Partition: pass 1 = app/envelope/errors/guards/listing/lookup/store/routes_reference/routes_advisor/routes_credential; pass 2 = routes_booking/routes_client/routes_claim; pass 3 = routes_settlement/calc. Each pass handed off notes to the next; later passes extended earlier passes' sentences rather than rewriting them.

**Totals:** PRD_FINALIZED.md 406 lines / 94,797 chars -> PRD_COMPLETED.md 406 lines / 107,460 chars (**+12,663 chars, +0 lines**, 42 lines revised in place, no new sections/paragraphs). Ambiguity-pins 39, mismatch-revisions 11.

### Pass 1 (infra + reference + advisor + credential) — 18 ambiguity-pins, 7 mismatch-revisions
- §2.1 — insert — ambiguity — empty-string header counts as absent; role compared case-sensitively — `guards.py:38-44`
- §2.2 — insert — ambiguity — `api_request_id` is `req_` + exactly 20 chars from uppercase letters and digits — `envelope.py:13-14`
- §2.2 — insert — ambiguity — `api_request_timestamp` is the one timestamp read from host wall time, not the logical clock — `envelope.py:20` / `store.py:67-69`
- §2.3 — insert — ambiguity — non-integer `limit`/`offset` (fraction, word, empty) also `ERR_INVALID_REQUEST` — `guards.py:214-231`
- §2.3 — insert — ambiguity — `created_at` ties broken by server creation sequence (insertion order); `has_more` is `offset + returned < total_count` — `store.py:139-141`, `envelope.py:40-46`
- §2.4 — insert — ambiguity — `created_at`/`updated_at` from the logical clock; client instants parsed permissively (trailing `Z`, explicit offset, offset-free as UTC, date-only as first instant) and normalised to UTC — `store.py:119-137,72-85`
- §2.5 — revise — mismatch — removed "supplier aging buckets" from the never-recomputed-on-clock-advance list; every supplier's buckets are in fact recomputed on each advance — `routes_reference.py:59-60`
- §2.5 — insert — ambiguity — "open claim" for `refreshed_claim_count` means `SUBMITTED` or `DENIED`, counted whether or not figures changed — `routes_reference.py:53-57`
- §2.8 band 3 — insert — ambiguity — endpoints with declared inputs require a body; the three no-input endpoints accept absent or `{}` interchangeably but reject any field — `guards.py:55-68`, `routes_advisor.py:150,198,246`
- §2.8 band 5 — revise — mismatch — on departure the path advisor's ownership check precedes resolution of the body's `transition_advisor_id`, so `ERR_OWNERSHIP_VIOLATION` wins over `ERR_ADVISOR_NOT_FOUND` — `routes_advisor.py:226-229`
- §2.8 band 16 — revise — mismatch — `ERR_SPLIT_TIER_UNRESOLVED` also reachable from activate, reinstate and departure/finalize — `routes_advisor.py:170-172`, `calc.py:237`
- §2.8 post-list — revise — mismatch — unrouted path returns `ERR_INVALID_REQUEST` at HTTP 404 and an undeclared method at 405, not 400; trailing slash insignificant — `app.py:28,40-52`
- §3.1 — insert — ambiguity — every `name` input non-empty and <=200 characters — `routes_reference.py:132,158,191`
- §3.1 — insert — ambiguity — supplying `PROBATION` as `program_status` on registration is `ERR_INVALID_REQUEST` — `routes_reference.py:204-205`
- §3.2 — insert — ambiguity — `email` non-empty, <=320 chars, uniqueness by exact byte equality (case-sensitive) — `routes_advisor.py:33,40-42`
- §3.2 — insert — ambiguity — when supersession does not fire the prior agreement stays `ACTIVE` beside the new one; "the advisor's `ACTIVE` agreement" means the earliest-created `ACTIVE` row — `routes_advisor.py:119`, `calc.py:74-76`
- §3.2 — insert — ambiguity — suspension `reason` required and non-empty but not persisted — `routes_advisor.py:183-184`
- §3.2 — revise — mismatch — reinstatement recomputes `production_ytd_provisional_cents` itself from the bookings in the clock's calendar year before re-deriving the tier — `routes_advisor.py:210`, `calc.py:219-238`
- §3.3 — insert — ambiguity — no ownership check on credential filing; an `Advisor` may file against any advisor id — `routes_credential.py:46`
- §3.3 — insert — ambiguity — `coverage_amount_cents` is an integer >= 0 — `routes_credential.py:56`
- §3.3 — insert — ambiguity — decision `note` may be empty, <=2000 chars, not persisted — `routes_credential.py:130`
- §3.7 — revise — mismatch — supplier aging recomputed on the list endpoint as well as the single read — `routes_reference.py:242-247`
- §3.9 — revise — mismatch — an ineligible successor at finalize is always `ERR_DEPARTURE_BLOCKED`, never `ERR_TRANSITION_ADVISOR_INVALID` — `routes_advisor.py:266-270`
- §3.9 — insert — ambiguity — departure-cascade link four fires only when link three actually moved at least one booking — `routes_advisor.py:310-314`
- §4 list-filter — insert — ambiguity — empty and unrecognised query params ignored; exact-equality matching with numeric ints and `true`/`false` booleans; null fields never match a filter — `listing.py:8-27`, `guards.py:238-242`

### Pass 2 (booking + client + claim) — 11 ambiguity-pins, 3 mismatch-revisions
- §2.8 band 3 — revise — ambiguity — extended pass 1's no-input list with booking confirmation and travel completion; claim resubmission added as the optional-single-field case whose body may be omitted — `routes_booking.py:160,202`, `routes_claim.py:124`
- §2.8 band 16 — revise — ambiguity — extended pass 1's tier-seeding list with `confirm`, `cancel`, `commission-receipt`, `commission-claims/{id}/resolve` — `routes_booking.py:183,278,322`, `routes_claim.py:190`
- §2.9 — insert — ambiguity — a recompute is not a mutation: advisor `version`/`updated_at` do not move when a booking/receipt/claim event refreshes production figures as a by-product — `routes_booking.py:183,278,322`, `routes_claim.py:189`
- §3.4 — insert — ambiguity — client `full_name` non-empty, <=200 chars — `routes_client.py:25`
- §3.4 — insert — ambiguity — trust-ledger `memo` required, may be empty, <=2000 chars, and *is* persisted — `routes_client.py:104`
- §3.6 confirmation — insert — ambiguity — the booking's own status test outranks the advisor-status and trust-balance preconditions — `routes_booking.py:166-177`
- §3.6 confirmation — insert — ambiguity — the swept ledger line's server-written `memo` text; a 0-cent deposit writes no line and does not move `Client.version` — `routes_booking.py:188-192`
- §3.6 traveled — insert — ambiguity — `ERR_INVALID_BOOKING_STATE` evaluated before `ERR_TRAVELED_TOO_EARLY` — `routes_booking.py:205-208`
- §3.6 cancellation — revise — mismatch — only `EXPECTED`/`RECEIVED` have a money-axis consequence (`CLAIMED`/`WRITTEN_OFF`/`CHARGED_BACK` left as they stand), and *every* branch including `PENDING` recomputes supplier aging and the advisor's provisional figure and tier — `routes_booking.py:273-287`
- §3.6 chargeback link two — insert — ambiguity — `chargeback_count` written either way but `Supplier.version` increments only on actual demotion — `routes_booking.py:227-232`
- §3.7 receipt — insert — ambiguity — `amount_cents` is an integer >= 0 (a nil remittance is legal) — `routes_booking.py:297`
- §3.7 claim filing — insert — ambiguity — `claimed_amount_cents` carries no request-shape bound (zero/negative -> `ERR_CLAIM_AMOUNT_MISMATCH`); on the `EXPECTED` path a not-yet-`TRAVELED` booking gives `ERR_INVALID_BOOKING_STATE` while an unarrived due date gives `ERR_INVALID_COMMISSION_STATE` — `routes_claim.py:23,37-42`
- §3.7 negotiation — insert — ambiguity — `denial_reason` required, non-empty, <=2000 chars, persisted; `note` optional/empty-allowed/<=2000/unpersisted with an omissible body; `denial_reason` cleared to null on resubmit — `routes_claim.py:104,125,138`
- §3.7 aging refresh — revise — mismatch — aging/escalation also refreshed on every read of an open (`SUBMITTED`/`DENIED`) claim, single and list, while resolved claims stay frozen at resolution — `routes_claim.py:82-84,90-92`
- §3.7 resolution — revise — mismatch — either resolution recomputes **both** production bases, not the final one alone — `routes_claim.py:189-190`

### Pass 3 (settlement + calc) — 10 ambiguity-pins, 1 mismatch-revision
- §3.8 opening — revise — mismatch — "all seven monetary totals at 0" -> "all **six**"; the run row carries exactly six money fields beside `statement_count` — `routes_settlement.py:30-42`
- §2.8 band 3 — insert (appended after pass 2's sentence) — ambiguity — settlement-run calculation and posting also declare no input field and take the same absent/empty-body latitude — `routes_settlement.py:150,243`
- §2.6 — insert — ambiguity — the product being rounded is formed exactly from the rate's decimal spelling, not a binary float, so the half-cent boundary is never lost to representation error — `calc.py:30-39`
- §3.5 tier selection — insert — ambiguity — the governing schedule falls back, when the advisor holds no `ACTIVE` agreement (post-departure), to the `ACTIVE`-or-`TERMINATED` agreement with the greatest `effective_date`, ties by `created_at` ascending; a terminated ladder keeps governing the tier fields — `calc.py:99-104` (closes pass 2's flagged gap)
- §3.8 pricing — insert — ambiguity — the final basis driving per-booking tier selection is recomputed at calculate time over the calendar year of the current logical clock, not read from stored `production_ytd_final_cents` nor narrowed to the run's period — `routes_settlement.py:57-79`
- §3.8 pricing — insert — ambiguity — each contributing booking's `version` increments by 1 and `updated_at` refreshes when `statement_id`/`settled_share_cents`/`settled_tier_level` are written — `routes_settlement.py:208-212`
- §3.8 chargeback — insert — ambiguity — each chargeback-set booking's `version` increments by 1 when `chargeback_recognized_at` is stamped — `routes_settlement.py:213-215`
- §3.8 chargeback — insert — ambiguity — the `tier_level_applied` pair is read *after* the refresh, resolved against the advisor's live schedule rather than any booking's pinned schedule, and populated from the ladder even for a `DEPARTED` advisor whose bookings priced at `post_departure_advisor_pct` with null `settled_tier_level` — `routes_settlement.py:73-79,184-188`
- §3.8 posting — insert — ambiguity — an empty run's `version` increments **twice** in the one request (posting, then immediate closure) — `routes_settlement.py:275,280`
- §3.8 payment — insert — ambiguity — `payment_reference` is a required non-empty string of at most 200 characters, validated but persisted nowhere — `routes_settlement.py:303-304`
- §3.8 payment — insert — ambiguity — the `ERR_RUN_NOT_POSTED` gate passes for a run in `POSTED` **or `CLOSED`**, so re-paying the last statement of a now-`CLOSED` run reports `ERR_INVALID_STATEMENT_STATE`, never `ERR_RUN_NOT_POSTED` — `routes_settlement.py:309`

### Pass 3's deliberate non-changes (unreachable or unobservable)
`refresh_claim_aging`'s negative-day floor (clock is monotonic); `pay_statement`'s untouched lifetime/consortium recomputes (both recompute over `POSTED`|`PAID`, so `POSTED->PAID` changes nothing observable); `host_platform_fee`/`cancellation_chargeback`/`tier_schedule_for` zero-fallbacks (activation requires exactly one `ACTIVE` agreement and FKs are validated); `recompute_client_balance` rewriting `balance_after_cents` (idempotent over an append-only stably ordered set, so §2.4's immutability claim stays observably true); `calc.final_tier_pct` is dead code. Pass 2's open `agreement_id: None` question is **closed** — settlement's only null-agreement paths (the `DEPARTED` `pct = 0` branch and the `ERR_SPLIT_TIER_UNRESOLVED` tier branch) are unreachable because departure link three re-pins to a successor holding exactly one `ACTIVE` agreement; §3.5 was left alone.

### Integrity check (whole document, pass 3)
```
  406  94797 PRD_FINALIZED.md
  406 107460 PRD_COMPLETED.md
headings:        29 / 29
endpoint rows:   47 / 47
error rows:      52 / 52
tail -5 ends on: | `ERR_CLOCK_REWIND_FORBIDDEN` | 422 |
heading-list diff (FINALIZED vs COMPLETED): IDENTICAL heading lists
```

Orchestrator verification: PRD_COMPLETED.md is NOT byte-identical to PRD_FINALIZED.md (42 lines differ, +12,663 chars) so the scan demonstrably ran; no `.py` under `implementation/`, `test_suite/` or `test_helpers/` was modified after the final sweep; `results.1..8.json` all still report `passed == total == 85`; no stray `worklog.md`, `__pycache__` or `.bak` anywhere in the task tree.
