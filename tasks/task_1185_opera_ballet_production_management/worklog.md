# Worklog — task_1185_opera_ballet_production_management

## Step 1: Create task directory — 2026-08-11T13:37:00.000Z

Pre-assigned output folder `tasks/task_1185_opera_ballet_production_management` with `workspace/` subdirectory already existed; auto-index scan skipped per instructions. Step 1 treated as done.

## Step 2: Generate scaffold — 2026-08-11T15:24:00.000Z

All three scaffold artifacts generated, cross-checked, and lint-clean.

## Summary

**Output files** (in `/home/ubuntu/github/CodingPRD/tasks/task_1185_opera_ballet_production_management/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single `scaffold_difficulty_design:` key
- `SCAFFOLD_CORNER_DESIGN.yaml` — single `scaffold_corner_design:` key

**Scale (expert+ band per the "harder than expert" instruction):**
- 16 entities, 80 endpoints, 34 error codes, 10 calculation rules, 11 state machines (62 transitions), 8 roles, 14 ordered validations
- §1.8: 9/9 difficulty rules, 19 instances (2 per rule, 3 for combinatorial_formula), 527 structured API calls across both design files
- §1.9: 9 sections, 46 instances (34 active + 12 `excluded_because` stubs)

**Key design decisions:**
- **Archetypes**: primary `temporal_windowing` (rehearsal rooms + singleton-stage changeover buffers), secondary `quota_allocation` (seat inventory); layers: cascading side effects, dual-variant calculation, OCC, rate/threshold triggers. Flat topology (`api_prefix: /opera`), cyclic state-machine headline, segregation-of-duties role model.
- **Rule differentiation**: dual variants in two domains (co-production settlement GROSS_COST vs NET_REVENUE_SHARE; artist pay PROJECTED vs FINAL); combinatorial formulas in all three modes (tiered overtime with night premium; pinned nested rounding for seat pricing — 15,076 vs naive 15,075; rental fee tier keyed on base not total); non-linear machines on RentalOffer (SENT↔COUNTERED cycle, round cap 5) and Performance (sales × readiness parallel dims); cascades from performance cancel (depth 3: inventory → season revenue → co-pro accrual) and principal release (cover promotion → casting_status); priority conflicts (state vs business_safety; business_referential vs business_safety); boundaries (rest floor exactly-12h; exact seat exhaustion); cross-entity gates (Performance←SurtitleTrack LIVE, RentalOffer←PartnerCompany standing); overlap rules with deliberately different interval semantics (half-open rooms vs buffered stage changeovers, 6h cross-production / 2h same-production); compensating invariants on seat count and build budget.
- **Compliance mechanics**: OCC on `Production.version` for rental-offer create-with-supersede (the one true race passing §1.2.1's filter); two SoD pairs (waiver approver ≠ contract creator; settle caller ≠ offer creator); entity-backed `PartnerRepresentative` role with renter-ownership checks; logical clock endpoint with the mandated `2026-05-01T00:00:00Z` default.
- All numeric assertions in test recipes were computed by executing the pinned formulas (verified via script); zero unbound `${var}` placeholders; no forbidden race vocabulary; all `excluded_because` stubs reference real §1.8 instances.

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (The single intermediate violation — the self-referential `CastAssignment.covers_assignment_id` lacking a reverse GET — was fixed by adding `covers_assignment_id?` to the cast-assignments filtered list.)

Verified on disk: SCAFFOLD.yaml (84716 B), SCAFFOLD_DIFFICULTY_DESIGN.yaml (77244 B), SCAFFOLD_CORNER_DESIGN.yaml (87814 B); all three parse as YAML with correct top-level keys.

## Step 3: Copy shared files — 2026-08-11T15:25:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1185_opera_ballet_production_management/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-11T15:58:00.000Z

All checks pass. Here is the final summary.

## Generated

**Output**: `/home/ubuntu/github/CodingPRD/tasks/task_1185_opera_ballet_production_management/workspace/PRD.md` — 350 lines, prose-style PRD for the Opera & Ballet Production Management API. The two forbidden DESIGN files were never opened.

### Section list
- **§1. Introduction** (2 paragraphs — domain/pain-point angle)
- **§2. Global Specifications & System-Wide Principles** (10 subsections):
  - 2.1 User and Role-Based Access Control (headers, 8 roles, opaque vs entity-backed `PartnerRepresentative` identity prose)
  - 2.2 API Response Structure (emitted **byte-verbatim** from `section-2.2-response-structure.md`, verified)
  - 2.3 Pagination (limit 10/1/100, offset 0, `created_at` ascending, meta fields)
  - 2.4 Common Resource Properties (UUID `id`, 3-fractional-digit timestamps, `version`; cross-entity version bumps)
  - 2.5 The Logical Clock (default 2026-05-01T00:00:00Z, never wall-clock; gates complete/settle)
  - 2.6 Monetary Precision and Rounding (three pinned rounding disciplines)
  - 2.7 Optimistic Concurrency on Rental Offer Creation (`expected_production_version` → `ERR_STALE_VERSION` 412; no race framing)
  - 2.8 Rooms, the Shared Stage, and Scheduling Conflicts (half-open vs buffered-adjacency semantics)
  - 2.9 Request Processing and Validation Order (all 14 priority tiers as an explicit ordered pipeline with endpoint scopes)
  - 2.10 Segregation of Duties
- **§3. Business Logic & Workflows** (9 subsections): partner companies & standing; productions & build pipeline (budget conservation); co-production shares (ratify/dispute/settle, both variants at equal density); artists, contracts & weekly pay (PROJECTED vs FINAL, overtime tiers, night premium); casting & cover chain (3 confirm guards in pipeline order, promotion cascade); rooms, calls & call sheets (rest floor, waiver path, headcount derivation); stage occupancy & surtitles; performances, readiness gate, sales dimensions, pinned seat pricing (with the 10050→15076 vs 15075 worked example from the scaffold); rental offers & negotiation (OCC, supersede, round cap, settle).
- **§4. Endpoint Definitions** — 4-column table, all 80 endpoints.
- **§5. Error Code Catalogue** — 2-column table, all 34 error IDs.

### Hard-contract audit results
- **Contract 1 (Field-Name Coverage): PASS** — 93/93 required names present in backticks (all `entities[].fields`, all endpoint `input`/`query_params` identifiers, plus response-field names like `projected_pay_cents`, `unit_price_cents`, `current_utc`).
- **Contract 2 (Rule Coverage): PASS** — 14/14 validation priorities expressed as an ordered pipeline; 1/1 OCC rule with endpoint + field + error + status; 11/11 state machines fully rendered (all transitions, preconditions, side effects incl. the 3-level cancel cascade and cover-promotion cascade); 10/10 calculations in precise prose (no pseudocode, no fuzzy words — verified by operator/fuzzy scans); all `applies_to` scopes enumerated with paths in §2.9; all defaults/initial values placed on owning entities; sibling branches (GROSS_COST/NET_REVENUE_SHARE, PROJECTED/FINAL, decline/withdraw/supersede sets) at equal density.
- **Contract 3 (§3 Path Purity): PASS** — 599 backticked tokens scanned in §3, even parity, 0 path tokens, 0 bare-method tokens, 0 method+path tokens.
- Cross-checks: 34/34 error IDs in §2/§3 prose and §5 table; 47/47 state values backticked; 8/8 roles backticked; 80/80 endpoint paths in §4; §2.2 verbatim PASS; 0 fuzzy words; 0 operator-bearing backtick tokens.

(Note: an early verification script reported false failures because shell heredocs mangled the backtick regex and code fences shifted token pairing; the final file-based verifier with fence-stripping confirms the true PASS results above.)

Verified on disk: workspace/PRD.md exists (350 lines).

## Step 5: Generate unit tests — 2026-08-11T16:40:00.000Z

Generation complete. Summary:

## Files written (19 files, ~168 KB)

**test_helpers/** (9 files, 67,001 B):
- `types.py` (9,572 B) — 16 entity TypedDicts (all `common_fields: true`), 20 status/role enums
- `api_client.py` (14,528 B) — `ApiClient(GenericApiClient)` with one method per PRD endpoint (72 methods)
- `api_errors.py` (4,033 B) — 34 `ApiErrorId` members + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` (8,802 B) — per-entity `assert_*` + `assert_build_budget_conservation` / `assert_seat_conservation` invariants
- `factories.py` (5,439 B) — 15 payload factories, input fields only
- `constants.py` (1,222 B) — OT tiers, night premium, section multipliers, demand tiers, rental threshold, buffers
- `test_users.py` (1,974 B) — shared headers for 7 opaque roles + `Any`; `make_partner_representative_headers` for the entity-backed role; per-instance PM/CO builders for SoD tests
- `fixtures.py` (29,947 B) — composite builders: state-progression, `create_active_contract`, `setup_confirmed_principal`/`setup_fully_cast_role`, pay-week scenarios, `setup_readiness_scenario`, `setup_net_share_performance`, `setup_copro_settlement_scenario`, rental-offer lifecycle with automatic OCC version threading
- `__init__.py` (1,056 B) — barrel export (framework + PRD-specific)

**test_suite/** (10 files, 97,946 B): `conftest.py` + 9 test files.

## Test counts
- **Queue A (Difficulty): 19/19 instances × 2 tests = 38 tests** — every instance has exactly 2.
- **Queue B (Corner): 34/34 non-stub instances × 1 test = 34 tests.**
- **Total: 72 tests**, collected cleanly by pytest.

## Skipped instances
None. All 19 difficulty instances and all 34 non-stub corner instances passed the PRD-first two-condition filter and were translated. The 12 `excluded_because` stubs (2 endpoints, 8 errors, 2 cross-cutting) were not translated; all 12 `difficulty_instance` cross-references resolve to real §1.8 instances.

Two adjudication notes (adaptations, not skips):
- `build_budget_conservation_order_cancel`: the YAML trigger chain transitions BUILT → CANCELLED, which no PRD-conformant implementation can allow (PRD §3.2 declares cancel only from `ORDERED`). The test inserts the PRD-declared `BUILT` → `ORDERED` rework loop before the cancel; all three pre-computed balance literals (70M / 68M / 100M) are asserted unchanged.
- `production_create_computed_and_system_fields`: the instance's `version == 1` sub-assertion is not uniquely derivable (PRD §2.4 pins increment semantics, not the initial value), so the test asserts version presence/type and all PRD-pinned values (balance, season revenue, DESIGN, UUID, timestamps) — per the sanctioned "drop the underivable sub-assertion" relaxation.

## Verdicts
- `py_compile`: PASS (all 19 files)
- Import check: PASS (all 9 test modules import with `test_helpers` on path)
- pytest `--collect-only`: **72 tests collected**
- Design-tag audit: PASS — every test has exactly one `Design:` tag as the final docstring line, resolving to a real instance in the correct queue/section
- Coverage audit: PASS — 0 shortfalls (D ≥2, C ≥1)
- PRD citation grep: PASS — every quoted `PRD §…` sentence fragment survives a whitespace-normalized literal grep of PRD.md (2 initial failures from a paraphrased duplicate-participant sentence were fixed to verbatim)
- Forbidden scans: PASS — no `pytest.mark.skip`/`skipif`/`xfail`, no "scaffold" references in generated code

Verified on disk: test_helpers/ 9 files, test_suite/ conftest.py + 9 test files, 72 test functions, all py_compile clean.

## Step 6: Generate implementation — 2026-08-11T16:40:00.000Z

Done. The implementation is complete and smoke-tested.

## Files written

All under `/home/ubuntu/github/CodingPRD/tasks/task_1185_opera_ballet_production_management/workspace/implementation/` (93,489 bytes total, ~2,300 lines):

| File | Bytes | Purpose |
|---|---|---|
| `start.sh` | 399 | Guarded pip install (`import flask` check) + `exec python3 app.py`, foreground |
| `requirements.txt` | 16 | `Flask>=2.0,<4.0` |
| `app.py` | 2,028 | Entry point, 17 blueprint registrations, envelope-ified error handlers, per-request store lock, `0.0.0.0:$PORT` (default 10000) |
| `db.py` | 1,219 | In-memory `Store`: 16 dicts + logical clock starting at exactly `2026-05-01T00:00:00Z`. No seeding, no disk |
| `errors.py` | 2,320 | `ApiError` + all 34 error-id constants from the catalog |
| `response.py` | 1,054 | Envelope: `meta{api_request_id, api_request_timestamp}`, `response_type` object/array/error, pagination fields in `meta` |
| `middleware.py` | 1,261 | `X-User-ID`/`X-User-Role` auth, 8 declared roles, RBAC |
| `util.py` | 7,811 | Datetime parse/format, `Decimal` round-half-up, field validators, pagination, record factory, `touch`/`refresh` |
| `services.py` | 10,597 | All 9 calculations: build balance, co-pro settlement (both variants), weekly pay + overtime tiers + night premium, pinned two-stage seat pricing, rental fee (tier keyed on base only), rest floor, room overlap, stage changeover, casting completeness |
| `routes/*.py` | 18 files | One blueprint per resource group |

## Endpoints
**80/80** — programmatic diff of Flask's `url_map` against SCAFFOLD.yaml §1.5: zero missing, zero extra.

## Key design decisions
- **Validation pipeline** follows PRD §2.9 exactly: auth → role → entity-backed ownership (rental counter/accept/decline) → shape → time-range → existence → OCC (`expected_production_version`, 412) → state → SoD → referential → scheduling conflicts → rest floor → capacity → fiscal (402).
- **Version discipline**: `version` bumps on direct mutations and cascaded child mutations, but `Production.version` bumps only on its own transitions, the `BUILT` cascade touch, and rental-offer creation — per PRD §2.4's exhaustive carve-out (verified: purchases/recomputes leave it unchanged, keeping OCC usable).
- **Pinned rounding**: seat pricing rounds twice (`rhu(base×section_mult)` then `rhu(unit×demand_mult)`) — verified against the PRD's 10050-cent BALCONY example (15076, not 15075); pay/rental fees round once at the end; build budget is exact integers. All money via `Decimal`.
- **Boundary semantics**: half-open room intervals (back-to-back allowed), stage changeover with 2h/6h buffers (exactly-buffer passes), rest floor `>=` passes, demand tiers at 0.5/0.8, group discount at quantity 10, negotiation cap 5, logical-clock gates (`>` ends_at for complete, `>=` window_end for settle).
- **Cascades**: terminate → participants REMOVED + headcount recompute; cancel → inventories zeroed → season revenue → RATIFIED NET-share accruals; release of a CONFIRMED principal → lowest-rank/earliest cover promotion with re-pointing.
- Fresh-process cleanliness: store is module-level dicts, empty at boot; no `seed_*`, no files written anywhere.

## Smoke test result
Booted via `bash start.sh` on ports 18711/18931 (foreground, `$PORT`, `0.0.0.0`, ready in <1s). Unauthenticated request → 400 `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` in the correct error envelope; fresh-boot list returns empty `data` with full pagination meta. Two scripted batches against the live server: **95 checks passed, 0 implementation failures** (the 6 initial red checks were all arithmetic/ordering typos in my throwaway scripts — group discount on the 60-seat purchase, 8+8+8+2=26h, clock already advanced — the server's actual values matched the spec in every case). Server shut down cleanly after each run; repeated relaunches confirmed empty-store boots.

Verified on disk: implementation/ with 18 route modules, all py_compile clean. Orchestrator route-diff (normalized path params): 80 declared == 80 registered, 0 missing, 0 extra — PASS.

## Step 7: Run tests and iterate — 2026-08-11T17:05:00.000Z

## Summary

- **Iterations run:** 4 sweeps total. Sweep 1 (baseline): 5 deterministic failures in every round. Sweep 2 (after fix): 8×72 passed on stdout but results files were consumed before verification (concurrent pipeline interference). Sweep 3: all assertions green, but 4 of 8 rounds each had 1 infrastructure error (`API server could not be restarted` — boot-poll timeout under load-avg 13 from a co-resident task_1186 sweep). Sweep 4: **all 8 rounds clean, 72/72 passed, 0 failed, 0 errors** — exit condition met.

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:** none.

- **Fixes applied to `implementation/`:** one fix.
  - `/home/ubuntu/github/CodingPRD/tasks/task_1185_opera_ballet_production_management/workspace/implementation/util.py`, `new_record()`: changed entity id minting from `uuid.uuid4().hex` (32 hex chars, no hyphens) to `str(uuid.uuid4())` (canonical hyphenated RFC 4122 form). Why: PRD §2.4 states verbatim "`id` is a server-minted UUID with no type prefix"; the standard textual representation of a UUID is the hyphenated 8-4-4-4-12 form, which is what the test helper's `is_valid_uuid` enforces. This single root cause accounted for all 5 baseline failures (`test_production_create_computed_and_system_fields`, `test_room_back_to_back_allowed_and_overlap_rejected`, both `TestStageChangeover` tests, `test_new_offer_supersedes_prior_sent_offer`) — each tripped `_assert_common_fields` in `test_helpers/assertions.py` on the malformed id before reaching its domain assertions.

- **Diagnostics per protocol:** STEP 0 identified one shared failure signature across all 5 tests. STEP 1a: PRD §2.4 verbatim-covers the rule ("server-minted UUID"). STEP 1b: uniquely derivable — "UUID" denotes the canonical hyphenated representation; a hyphen-less `.hex` rendering is a non-standard choice a faithful reader would not produce. STEP 2: test artifact faithful (assertion traces to §2.4 verbatim). STEP 3: implementation fixed; no PRD-required check weakened, no data seeded, storage remains in-memory only.

Orchestrator verification on disk: 8 results files (results.1–8.json, all timestamped 17:02), each total=72 passed=72 failed=0 errors=0 — ALL 8 ROUNDS PASS confirmed.

## Step 8: Finalize PRD — 2026-08-11T17:15:00.000Z

Analysis complete. All prior pipeline tasks are done; no new tracking needed for this zero-edit outcome.

## Summary

**PRD_FINALIZED.md produced at** `workspace/PRD_FINALIZED.md` — byte-identical to PRD.md. **Zero edits were warranted.**

### Line counts and delta
- PRD.md: 349 lines; PRD_FINALIZED.md: 349 lines; **0% delta** (diff confirms IDENTICAL).

### Changes
- **None.** The `<step_7_diff>` lists exactly one item (no test deletions, no test_helper/test_suite fixes): `implementation/util.py` `new_record()` id minting changed from `uuid.uuid4().hex` to `str(uuid.uuid4())` (`util.py:197`). That item reveals **neither PRD-silence nor PRD-mismatch** — it is a pure implementation bug fixed toward the PRD:
  - PRD §2.4 (line 74) states verbatim: "`id` is a server-minted UUID with no type prefix." The rule is present, not silent.
  - Step 7's own STEP 1a/1b diagnostics concluded the PRD verbatim-covers the rule and the hyphenated form is **uniquely derivable** — "UUID" denotes the canonical hyphenated 8-4-4-4-12 representation; the hyphen-less `.hex` rendering was a non-standard choice a faithful reader would not produce.
  - Post-fix, implementation and PRD agree; per method step 2 ("where PRD already determines behavior, keep prose verbatim") and the hard scope ("every PRD edit must trace to PRD-silence or PRD-mismatch"), no patch is justified.

### Per-edit pre-edit search log (one candidate edit evaluated and rejected)
- **(a) Subject:** textual representation of the server-minted `id` field (PRD §2.4).
- **(b) Impl paths enumerated:**
  - `implementation/util.py:197` — the **sole** id-minting site (`"id": str(uuid.uuid4())`); a repo-wide grep for `uuid`/`uuid4`/`hex` across `implementation/` (excluding `__pycache__`) returned only this site plus its import.
  - All 17 `new_record()` callsites across `implementation/routes/*.py` and `implementation/services.py` — every entity's id funnels through the one minting site.
  - All remaining `"id"` references in `services.py` and `routes/` are foreign-key lookups/equality comparisons — none mint ids, so no off-site path could contradict §2.4 wording.
  - External enforcement confirmed: `prd_bench_local_runner/testing/assertions.py:19-21` — `_UUID_RE = ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$` (case-insensitive), i.e. hyphens required; consumed by `_assert_common_fields` in `test_helpers/assertions.py:7`.
- **(c) Wording adjustment:** none — the edit itself was rejected. Adding representation detail (e.g., "canonical hyphenated 8-4-4-4-12 form") was considered and rejected: the PRD already uniquely determines the behavior, so any insertion would be a non-minimal change untraceable to PRD-silence or PRD-mismatch, violating the hard scope.

**Conclusion:** A fresh implementer reading PRD_FINALIZED.md (== PRD.md) and faithfully implementing "server-minted UUID" produces the standard hyphenated UUID the implementation now emits; PRD and `implementation/` are behaviorally aligned with zero PRD changes.

Orchestrator verification on disk: workspace/PRD_FINALIZED.md exists, diff vs PRD.md confirms byte-identical.

## Step 9: Complete PRD — 2026-08-11T17:35:00.000Z

The patch is complete: 349 → 349 lines (all changes are in-paragraph, as required), 57115 → 60407 chars (+3292). 21 lines revised, carrying 22 logical changes. Verification that the file was only edited inline and no sections added: line count identical, all diff hunks are single-line replacements.

## Summary

**Source**: `workspace/PRD_FINALIZED.md` (identical to `PRD.md`) → `workspace/PRD_COMPLETED.md`
**Line counts**: 349 → 349 (no new paragraphs or sections; all inserts inline)
**Char delta**: +3292 (57115 → 60407)
**Counts**: 19 ambiguity-pins, 3 mismatch-revisions (22 changes total; one paragraph line carries two)

### Ambiguity pins (19)

- §2.3 — insert — ambiguity — pinned `offset` non-negativity, non-integer/out-of-range `limit`/`offset` → `ERR_VALIDATION` (400), and `created_at` ties broken by creation order — implementation/util.py:170-188, routes/common.py:30
- §2.4 — insert — ambiguity — pinned `version` starts at 1 and `updated_at` initially equals `created_at`; derived-field recomputes (`build_cost_balance_cents`, `season_revenue_cents`, `casting_status`, `confirmed_headcount`, `accrued_revenue_share_cents`) refresh only `updated_at`, only when the value changes, and never bump `version` — implementation/util.py:195-221, services.py:25-57,82-107
- §2.9 step 3 — insert — ambiguity — the offer id is resolved first (missing offer → `ERR_NOT_FOUND` 404) before the renter-ownership comparison — implementation/routes/rental_offers.py:163-168
- §2.9 step 4 — insert — ambiguity — pinned body parsing (absent body = empty object; unparseable/non-object body = `ERR_VALIDATION`), datetime input normalization (offset honored, naive read as UTC, unparseable = `ERR_VALIDATION`) and response rendering (UTC, second precision unless sub-second supplied), and the `to_state` domain rule (must be a target of a declared transition, else `ERR_VALIDATION`; declared-but-unreachable falls to step 8) — implementation/util.py:32-46,68-82, routes/*.py TARGET_STATES/_ALLOWED
- §3.1 — insert — ambiguity — re-submitting the current standing is accepted as a no-op value change (`updated_at`/`version` still advance) — implementation/routes/partner_companies.py:49-52
- §3.2 — insert — ambiguity — `actual_cost_cents` is read only when the target state is `BUILT` and ignored on other transitions — implementation/routes/build_items.py:66-69
- §3.3 — insert — ambiguity — `share_percentage` is a JSON number with fractional values allowed — implementation/routes/co_production_shares.py:47-50, util.py:154-163
- §3.4 — insert — ambiguity — `rest_floor_hours` is a non-negative integer (zero allowed), default 12 — implementation/routes/contracts.py:32
- §3.4 — insert — ambiguity — `week_start` time-of-day is discarded (window opens 00:00:00 UTC on the named date); missing/unparseable `week_start` or out-of-range `mode` → `ERR_VALIDATION` — implementation/routes/contracts.py:128-136
- §3.5 — insert — ambiguity — cover-promotion tie-break extended: identical `created_at` broken by creation order — implementation/routes/cast_assignments.py:147-148
- §3.6 — insert — ambiguity — room `hourly_rate_cents` must be a non-negative integer — implementation/routes/rehearsal_rooms.py:24
- §3.6 — insert — ambiguity — `required_headcount` is a non-negative integer defaulting to 1 — implementation/routes/rehearsal_calls.py:33
- §3.6 — insert — ambiguity — the publish-time room-overlap re-check excludes the call being published — implementation/routes/rehearsal_calls.py:88-89
- §3.8 — insert — ambiguity — `sections` must be non-empty; `section` ∈ {STALLS, BALCONY, BOX, GALLERY}; `total_seats` positive integer; `base_price_cents` non-negative integer; malformed elements → `ERR_VALIDATION` — implementation/routes/performances.py:23-52
- §3.8 — insert — ambiguity — cancellation requires the performance `SCHEDULED`, else `ERR_INVALID_STATE_TRANSITION` — implementation/routes/performances.py:233-235
- §3.8 — insert — ambiguity — price-quote `quantity` is a positive integer defaulting to 1, else `ERR_VALIDATION` — implementation/routes/seat_inventories.py:41-49
- §3.8 — insert — ambiguity — hold/release/purchase `quantity` must be a positive integer, else `ERR_VALIDATION` — implementation/routes/seat_inventories.py:61-63
- §3.9 — insert — ambiguity — `countered_fee_cents` must be a positive integer — implementation/routes/rental_offers.py:176
- §3.9 — insert — ambiguity — `fee_base_cents`/`surcharge_pct`/`total_fee_cents` stay null until first send, `countered_fee_cents` until first counter, `final_settlement_cents` until settlement — implementation/routes/rental_offers.py:68-72, services.py:160-166

### Mismatch revisions (3)

- §3.3 — revise — mismatch — "net variant yields a strictly smaller settlement than gross on identical inputs" → never settles above gross and is strictly smaller only when the accrued revenue share is positive (accrual of zero makes them equal) — implementation/services.py:64-75
- §3.4 — revise — mismatch — "strictly lower final pay whenever any `PUBLISHED` call exists" → strictly lower only when an *included* call (contract participates `CONFIRMED`/`CHECKED_IN`, starts in window) is still `PUBLISHED` — implementation/services.py:237-256
- §4 — revise — mismatch — pay-quote row claimed "`mode` selects the inclusion set"; impl validates `mode` but always reports both variants — implementation/routes/contracts.py:124-137, services.py:278-286

Everything else in the implementation — the 14-step validation pipeline order per endpoint, both conflict checks (half-open room, buffered stage), the two-stage seat-price rounding, fee-schedule tiering on fee base, rest-floor pair semantics, OCC on offer creation, supersede/cancel/termination cascades, SoD gates, all filters, and the §5 error catalog — was already uniquely pinned by the PRD and left untouched.

Orchestrator verification on disk: workspace/PRD_COMPLETED.md exists (349 lines). Pipeline complete: all 8 sweep rounds pass (72/72 each), worklog reaches Step 9, PRD_COMPLETED.md present.
