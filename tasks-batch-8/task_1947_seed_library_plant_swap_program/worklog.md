## Step 2: Generate Scaffold — 2026-08-15T03:13:10.000Z

All three files exist, parse as valid YAML, and pass `scaffold_lint.py` with a clean verdict. Summary:

**Files written:**
- SCAFFOLD.yaml (§1.0–§1.7 only; no design keys)
- SCAFFOLD_DIFFICULTY_DESIGN.yaml (single key `scaffold_difficulty_design`)
- SCAFFOLD_CORNER_DESIGN.yaml (single key `scaffold_corner_design`)

**Counts:** 13 entities, 69 endpoints, 28 error codes, 8 calculations, 11 state machines, 26 ordered validation rules, 3 roles, 2 OCC concurrency rules. §1.8: **19 difficulty instances** (every rule ≥2; combinatorial_formula has 3 covering modes a/b/c). §1.9: **57 corner instances (42 non-stub, 15 excluded_because stubs)** across all nine guide sections.

**Lint verdict (verbatim):** VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.

**Notable design decisions:**
- Archetype: quota/allocation primary (seed stock, packet allocation min-of-4 formula, borrow caps, session capacity) + compliance/audit secondary (invasive screening, germination certification with segregation of duties: Volunteer records, ProgramAdmin certifies).
- Dual-variant calcs on different domains: lot viability (PROVISIONAL 80%→800 vs CERTIFIED_FINAL 90%→900 on identical stock) and member return rate (SIMPLE 0.5 vs DECAY_WEIGHTED 0.6667, half-life-90d weights over clock-controlled checkout ages — all numbers verified by Python before writing).
- Combinatorial formulas in 3 distinct modes: (a) pack allocation min(seed-floor, labels, lot-cap) with certification-state branch; (b) swap-credit per-item round-then-sum (pinned: two 4.5→5 items sum to 10, not 9); (c) borrow-limit derivation with pinned evaluation order (terminal-only rate → tier → limit; in-flight checkout never participates).
- Two cyclic state machines (SeedLot ACTIVE⇄QUARANTINE recheck loop; Checkout RETURNED⇄DISPUTED dispute loop) and two transitive cascades (certify-FAIL depth-3: lot→packets→checkout recall flags; event-cancel depth-2: items→REVOKED credit entries).
- Two compensating invariants on different quantities: lot seed-count conservation (received == remaining + in_packets + discarded, pack↔void-REINTEGRATE round trip) and credit-unit conservation via append-only CreditEntry ledger (earn↔revoke on cancel).
- Three interval-overlap semantics on two resources: swap events per site (30-min buffered half-open), packing sessions per site (plain half-open, back-to-back allowed), volunteer double-booking (closed intervals — touching endpoints conflict).
- OCC on SeedVariety.version and SwapEvent.version PATCH endpoints only; all other apparent races classified as state preconditions.
- Logical clock endpoint with pinned startup default 2026-08-01T00:00:00Z; overdue sweep uses strict < (due_at == now does not flip), suspension at exactly 3 overdue.

One issue during generation: an in-place regex post-processing script truncated the two design files mid-error; both were fully rewritten from the verified draft and re-linted clean. (Note: the subagent's first turn ended after planning without writing files; orchestrator resumed it via SendMessage to complete the writes.)

## Step 3: Copy Shared Files — 2026-08-15T03:13:14.000Z

Copied ./INSTRUCTION.md to tasks/task_1947_seed_library_plant_swap_program/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-15T03:27:03.000Z

All contracts verify. The PRD is complete at workspace/PRD.md.

A prose PRD for the Seed Library & Plant Swap Program API, structured as: §1 Introduction (2 paragraphs, program-context angle), §2 Global Specifications (10 subsections: RBAC with per-role identity anchoring, the verbatim §2.2 envelope block, pagination, identity/timestamps/versioning including the CreditEntry append-only exception, the logical clock with the 2026-08-01T00:00:00Z startup default, precision/rounding, OCC, nested-path resolution, the full 14-band validation evaluation order, and the two conservation invariants), §3 Business Logic (7 lifecycle-grouped subsections with rules scattered across them, no endpoint paths), §4 endpoint table (69 rows, 4 columns), §5 error catalogue (28 rows, 2 columns).

Key scaffold content carried into prose: the pinned four-step borrow-limit evaluation (rate → tier → limit → strict admit, in-flight attempt excluded), the 90-day-half-life decay-weighted score, the three-ceiling pack allocation (viable seeds / label stock / 200-packet lifetime cap), per-item-then-sum swap credit valuation (bases 2/5/3, multipliers 1.5/1.0/0.5, rarity +2, cap 25 with exactly-at-cap admitted and whole-submission rejection), the three-hop certify-FAIL recall cascade and two-hop cancel cascade, the two-pass daily sweep (strict due_at boundary; exactly-3 suspension; members_reinstated_count always 0), and both OCC rules (expected_seed_variety_version, expected_swap_event_version → ERR_STALE_VERSION 412). The forbidden SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were never opened.

Hard Contract Reports:
- Field coverage check: entities[].fields 65/65 present; endpoints[].input/request_body 47/47 present. Status: PASS
- Rule coverage check: 14/14 validation bands in prose; 2/2 OCC rejections; 43/43 state transitions; 8/8 calculations (constants embedded: 70.00, 21 days, 3, 200, 25, 90-day half-life, 2/5/8 limits, 30-minute buffer); 28/28 error ids; 69/69 endpoint side effects; defaults/initials all stated; 8/8 sibling-branch symmetry groups equal density. Status: PASS
- Path purity check (§3 only): 458 backtick tokens scanned, 0 path tokens, 0 bare HTTP-method tokens. Status: PASS

One process note: the subagent's first verification script mis-paired backticks because it didn't strip the fenced JSON blocks in §2.2 before extracting inline tokens — after stripping code fences, all mechanical checks pass cleanly.

## Step 6: Generate Implementation — 2026-08-15T03:58:20.000Z

Clean — no seeding anywhere, start.sh is executable, store starts empty (verified by fresh-boot smoke tests returning empty lists). The implementation is complete.

**Files written** (all under workspace/implementation/): start.sh (guarded launcher, skips pip install when flask importable, exec python3 app.py, binds 0.0.0.0:$PORT default 10000); requirements.txt (flask>=3.0,<4.0); app.py (Flask app factory, blueprint registration, envelope-compliant error handlers); db.py (in-memory store, empty at boot, logical clock pinned at 2026-08-01T00:00:00Z startup default, ISO8601 3-fractional-digit Z formatting, UUID ids, insertion sequence for created_at-ascending ordering); errors.py (all error IDs with exact HTTP statuses); response.py (envelope meta.api_request_id req_ prefix, response_type object/array/error, pagination fields in meta); middleware.py (X-User-ID/X-User-Role auth band 1, role permission band 2); validate.py (band-4 body shape validation with ERR_INVALID_REQUEST vs ERR_INVALID_ENUM split, pagination default 10/min 1/max 100); services/core.py (all calculations: germination viability PROVISIONAL/CERTIFIED_FINAL 2dp half-up floor, member return rate SIMPLE 4dp + DECAY_WEIGHTED 90-day half-life via Decimal, tier derivation TRUSTED≥5 terminals & ≥0.90 / PROBATION≥3 & <0.60 / STANDARD with limits 8/2/5, pack allocation min of seed/label/200-cap ceilings, swap credit per-item half-up rounding before summation with rarity +2 and 25 cap, credit ledger reconciliation, buffered/half-open/closed-interval overlap checks, lot depletion auto-check); routes/ (ops.py clock+daily sweep with due_at-ASC/created_at-ASC pass 1 + created_at-ASC suspension pass 2 strict < boundary; sites, members, volunteers, varieties OCC, lots+germination tests+certify/void+recall cascade+pack, packets void REINTEGRATE/DISCARD+dispose, checkouts create/return/verify/dispute/resolve with write-off cascade and auto-reinstate, swap_events full lifecycle with OCC PATCH + complete/cancel cascades with EXPIRED/REVOKED ledger entries + redeem, intake_items submit with screens/dup/cap + screen + withdraw + credit-entries reads, packing sessions+assignments+cancel/complete cascades+double-booking closed-interval+capacity).

**Endpoint coverage**: all scaffold endpoints implemented, role lists matching exactly.

**Design decisions where PRD prose required interpretation**:
1. Band-14 terminal lockdown placement — state checks (band 6) apply only to non-terminal entities; terminal lockdown evaluated last (non-owner member returning an already-VERIFIED checkout gets ERR_SELF_SERVICE_FORBIDDEN; stale-version PATCH on a terminal swap event gets ERR_STALE_VERSION rather than ERR_ALREADY_TERMINAL).
2. Recalled-packet return path — RECALLED packets never return to circulation: return/verify of a checkout holding a recalled packet proceeds to VERIFIED but the packet stays RECALLED (seeds stay in-packets) until /dispose moves them to discarded; verify-time DISCARD applies only to packets actually in RETURNED with a non-ACTIVE lot.
3. Duplicate member/volunteer email — catalog defines no dedicated error ID; reused ERR_DUPLICATE_LOT_CODE at 409 as the only uniqueness error ID.
4. No-op PATCH on lots — returns 200 with version bump; PATCH on a terminal lot always ERR_ALREADY_TERMINAL.
5. viable_seed_count computed on every read using final_viability_pct when any CERTIFIED test exists (VOIDED excluded), else provisional.
6. Overdue counting fully derived from checkout statuses in recompute_member (verify/write-off decrement falls out naturally; sweep idempotent).

**Verification**: three e2e rounds (~90 assertions) against fresh-booted servers all pass — recall cascade, depletion auto-transition, retire cascade, tier transitions (PROBATION at 3 terminals/0.0 rate, TRUSTED at 5/1.0), overdue boundary (due_at == now does not flip), suspension at exactly 3 overdue, auto-reinstatement, credit cap exactly-at-25 admission, cancel-blocked-after-redemption, event expiry, buffered-overlap half-open boundary, session back-to-back allowed + closed-interval double-booking touch, OCC stale/fresh on both guarded endpoints, result_pct 70.00 PASS boundary.

## Step 5: Generate Unit Tests — 2026-08-15T03:59:14.000Z

All checks pass. Generation complete.

Test infrastructure + suite generated from the two design indices only.

### Test counts
- Queue A (Difficulty): 38 tests covering all 19 instances at exactly 2 tests each (rule combinatorial_formula has 3 instances: modes a/b/c; the other 8 rules have 2 each).
- Queue B (Corner): 42 tests covering all 42 non-stub instances at 1 test each. The 15 excluded_because: stubs were not translated; every stub's difficulty_instance cross-reference verified to resolve to a real §1.8 instance.
- Total: 80 tests across 10 files (test_01 germination/lot lifecycle, test_02 catalog/packing/packets, test_03 borrow limits/member standing, test_04 checkout lifecycle, test_05 sweep/return rates, test_06 swap intake/credit ledger, test_07 swap event lifecycle, test_08 packing sessions/volunteers, test_09 security/validation/reads, test_10 recall cascade).

### Instances skipped
None fully skipped. Four sub-assertion relaxations under the two-reader rule (instance cores kept):
1. entity_member_creation_defaults_applied — dropped version == 1; PRD §2.4 never pins the initial version value.
2. Both OCC instances — absolute versions (== 2, == 3) relaxed to observed+1 relative assertions; the ERR_STALE_VERSION rejection (the core claim) is asserted exactly.
3. swap_event_buffered_interval_overlap — rejection asserted at creation instead of publish: PRD §3.6 states "The check runs at creation, again at publish, and again on any reschedule that moves the times," so a PRD-faithful server can never hold an overlapping DRAFT to publish. The half-open 12:30 adjacency claim is asserted via create+publish.
4. ep_pagination_limit_bounds — dropped limit=0/101 → ERR_INVALID_REQUEST (PRD states min 1/max 100 but never names the rejection error; clamping is a plausible faithful reading). Kept the derivable limit=2 paging assertion.
5. due_at exact-string assertions relaxed to instant comparison (PRD §2.4 prescribes three fractional digits, so a .000Z rendering is also faithful).

### Helper files written (test_helpers/)
types.py (12 status enums + 13 TypedDicts; CreditEntry carries only id/created_at per PRD §2.4), api_client.py (60 endpoint methods), api_errors.py (28 error ids + HTTP map registered via set_error_http_status_map), assertions.py (13 entity assertions + seed/credit conservation checkers), factories.py, constants.py, test_users.py (opaque admin constant; per-instance make_member_headers/make_volunteer_headers builders used for every ownership-gated call), fixtures.py (lot lifecycle, terminal-history builder, intake-open events, sweep/clock helpers — packet ids always taken from pack responses, never list positions, avoiding created_at tie-ordering), __init__.py barrel.

### Self-check results
- Stage 1: compileall clean; test_helpers imports cleanly against the installed framework.
- Stage 2: pytest --collect-only → 80 tests, 0 import errors; pyflakes clean (caught and fixed one real bug — missing create_site import in test_03); every test docstring ends with exactly one Design: line; all 80 tags resolve to real instances (no stub/dual/unknown tags); 112/112 PRD citations grep verbatim against PRD.md; no skip/skipif/xfail markers; no scaffold references in generated code.

## Step 7: Run Tests and Iterate — 2026-08-15T04:07:39.000Z

All 8 rounds pass 80/80. The exit condition is met.

**Iterations run:** 2 (baseline sweep → fix → verification sweep; all 8 parallel rounds green at 80/80 each).

**Tests deleted:** None. Both failing tests traced to verbatim PRD rules; their assertions were correct — only their setups were unfaithful.

**Fixes applied to `test_suite/` (2 — both STEP 2 test-setup bugs, not implementation bugs):**

1. `test_suite/test_02_catalog_packing_and_packets.py` — `TestPackEdgeCases::test_pack_rejected_when_seed_ceiling_floors_to_zero`. The setup certified PASS on a 50/100 = 50.00% assay, which PRD §3.3 forbids ("PASS requires a `result_pct` of at least 70.00") — an ACTIVE lot at 50.00% certified viability is unreachable under PRD, so the server correctly failed the setup with `ERR_VIABILITY_OUTCOME_MISMATCH`. Changed the fixture numbers to `seeds_received=10`, `certified_sprouted=70` (70.00%, the lowest PASS-band figure): the lot reaches ACTIVE legitimately, `viable_seed_count` is still `floor(10 × 0.70) = 7`, and the asserted rule (`floor(7/10) = 0` allocatable → `ERR_PACK_QUANTITY_EXCEEDS_ALLOCATABLE`) is unchanged.

2. `test_suite/test_07_swap_event_lifecycle.py` — `TestBufferedOverlap::test_event_starting_exactly_at_buffer_end_allowed`. The test created the second event at 12:30-13:30 against an existing 10:00-12:00 event; the new event's buffered interval [12:00, 14:00) genuinely intersects the existing [09:30, 12:30) over [12:00, 12:30), so the server's `ERR_EVENT_WINDOW_OVERLAP` was correct. PRD §3.6's half-open adjacency ("one event's buffered end landing exactly on another's buffered start is permitted") requires the new event's *buffered* start to equal 12:30, i.e. `start_at` 13:00. Changed to 13:00-14:00 and corrected the docstring's interval description.

**Fixes applied to `test_helpers/`:** None needed.

**Fixes applied to `implementation/`:** None needed — the implementation was already PRD-faithful; both failures were the tests violating PRD preconditions (a certification-outcome rule and the buffered-overlap geometry).

## Step 8: Finalize PRD — 2026-08-15T04:11:19.000Z

Done. PRD_FINALIZED.md is written as an exact copy of PRD.md with **zero edits** — the correct outcome for this task, since both Step 7 items were pure test-fixture bugs and the implementation already matches verbatim PRD rules at every enumerated path.

**Line counts / %-delta:** PRD.md = 308 lines, PRD_FINALIZED.md = 308 lines, 0% delta (byte-identical copy at workspace/PRD_FINALIZED.md).

**Changes:** None. Both <step_7_diff> items traced to verbatim PRD rules that the implementation already follows exactly; the failing tests were fixtures violating PRD preconditions. No PRD silence and no PRD/impl mismatch exists at either site, so no patch was warranted.

**Per-item pre-edit search log (mandatory (a)/(b) enumeration performed for both; both concluded "no edit needed"):**

1. Step 7 item 1 — test_pack_rejected_when_seed_ceiling_floors_to_zero fixture fix
   - (a) Subject: certification outcome agreement (PASS/FAIL band), viable_seed_count computation, and the pack-allocatable seed ceiling.
   - (b) Impl paths enumerated and read: implementation/services/core.py:8 (VIABILITY_PASS_PCT = Decimal("70.00")), core.py:31-40 (effective_viability, compute_viable_seed_count = floor of loose × pct / 100), core.py:43-50 (lot_view recomputes on every read), implementation/routes/lots.py:239-285 (certify_test: PASS with rp < 70.00 → ERR_VIABILITY_OUTCOME_MISMATCH/422; FAIL with rp ≥ 70.00 → same), lots.py:324-377 (pack_lot: allocatable = min(viable // seeds_per_packet, label_stock, 200 − packets_created_total); admits only 1 ≤ packet_count ≤ allocatable else ERR_PACK_QUANTITY_EXCEEDS_ALLOCATABLE/422). Repo-wide greps for VIABILITY_PASS_PCT, ERR_VIABILITY_OUTCOME_MISMATCH, viable_seed_count, PACK_QUANTITY confirmed no other touch points.
   - (c) Wording adjustment: none — PRD §3.3 ("PASS requires a result_pct of at least 70.00, and FAIL requires one strictly below 70.00; disagreement is rejected with ERR_VIABILITY_OUTCOME_MISMATCH"; "rounded down to a whole seed... on every read of the lot"), §3.4 (three ceilings, "smallest of the three", "at least 1 and at most that allocatable figure"), and §2.6 ("viable seed estimates... pack-allocation ceilings — are rounded down") already uniquely determine every enumerated impl behavior. The original fixture (certify PASS at 50.00%) was simply unreachable under the PRD.

2. Step 7 item 2 — test_event_starting_exactly_at_buffer_end_allowed fixture fix
   - (a) Subject: swap-event buffered-overlap geometry (±30-minute buffer, half-open adjacency) and when the check runs.
   - (b) Impl paths enumerated and read: implementation/services/core.py:182-198 (event_buffered_overlap: [start−30m, end+30m) per event, conflict iff bs < obe and obs < be — exactly half-open intersection, so bs == obe adjacency passes; skips CANCELLED events and the excluded self-id), implementation/routes/swap_events.py:35-38 (_check_overlap → ERR_EVENT_WINDOW_OVERLAP/409) with all three call sites: create (swap_events.py:55), publish (:136, self-excluded), and reschedule when times change (:111-112, self-excluded). Greps for event_buffered_overlap, EVENT_WINDOW_OVERLAP, timedelta confirmed the only other timedelta use is checkout due_at (+21 days), unrelated.
   - (c) Wording adjustment: none — PRD §3.6 ("each event claims an interval from thirty minutes before its start until thirty minutes after its end, and that buffered interval must not intersect any other non-CANCELLED event's buffered interval at the same site. The check is half-open — one event's buffered end landing exactly on another's buffered start is permitted... runs at creation, again at publish, and again on any reschedule that moves the times") pins exactly the impl semantics, including the "any other" self-exclusion the impl applies at publish/patch. The original fixture (new event 12:30–13:30 → buffered [12:00, 14:00) intersecting existing [09:30, 12:30)) was a genuine overlap the server correctly rejected; the corrected fixture (13:00–14:00, buffered start 12:30 == buffered end 12:30) is precisely the PRD's permitted adjacency.

No edits were committed, so no post-edit consistency verification was required; the file comparison confirms PRD_FINALIZED.md is byte-identical to PRD.md.

## Step 9: Complete PRD — 2026-08-15T04:24:59.000Z

All changes are in place and verified against the implementation. The diff touches 13 line-regions, all in-paragraph inserts/revisions, no new sections.

**Source vs output:** PRD_FINALIZED.md (308 lines / 50,035 chars) → PRD_COMPLETED.md (310 lines / 52,922 chars), char-delta **+2,887** (line +2 comes from the one standalone sentence-paragraph after the §3.3 certification bullets).

**Counts:** 14 ambiguity-pins (inserts), 7 mismatch-revisions.

**Changes (one per bullet):**
- §2.3 — insert — ambiguity — pins invalid limit/offset query values (non-integer, out-of-range, negative) rejected with ERR_INVALID_REQUEST — implementation/validate.py:154-175
- §2.3 — insert — ambiguity — pins has_more formula: true exactly when offset + returned page size < total_count — implementation/response.py:32
- §2.3 — revise — mismatch — list ordering changed from "created_at ascending" to creation (insertion) order, which only coincides with created_at order while the settable logical clock never moves backward — every list route sorts by _seq, e.g. implementation/routes/sites.py:60
- §2.3 — insert — ambiguity — enum-valued filter params (status, category, entry_type) reject out-of-set values with ERR_INVALID_ENUM — implementation/routes/sites.py:57-59 (same pattern in all 12 list endpoints)
- §2.4 — insert — ambiguity — version starts at 1 on creation — implementation/db.py:83
- §2.4 — insert — ambiguity — any accepted write, including a no-op PATCH changing no field, advances version/updated_at — implementation/db.py:94-97, routes/sites.py:102, routes/lots.py:120-123
- §2.9 band 4 — insert — ambiguity — adds seeds_per_packet at least 1 to the shape-validation numeric list — implementation/routes/lots.py:330
- §2.9 band 4 — insert — ambiguity — unconsumed extra body fields are ignored — implementation/routes/checkouts.py:198 and all handlers
- §2.9 note — revise — mismatch — terminal lockdown fires when evaluation *reaches* band 14; earlier bands (shape, fiscal, ownership, OCC) still run first and mask ERR_ALREADY_TERMINAL — implementation/routes/swap_events.py:114-119 and 277-285, routes/intake_items.py:63-91
- §3.1 — insert — ambiguity — duplicate member email rejected with ERR_DUPLICATE_LOT_CODE (409), the reused uniqueness identifier — implementation/routes/members.py:42-45
- §3.1 — insert — ambiguity — duplicate volunteer email draws the same ERR_DUPLICATE_LOT_CODE (409) — implementation/routes/volunteers.py:30-33
- §3.3 — insert — ambiguity — recording an assay requires X-User-ID to resolve to an existing volunteer (ERR_NOT_FOUND) and that volunteer to be ACTIVE (ERR_INVALID_STATE) — implementation/routes/lots.py:183-188
- §3.3 — revise — mismatch — "recording against a lot in any other state" qualified: non-terminal states draw ERR_INVALID_STATE, terminal lots draw ERR_ALREADY_TERMINAL — implementation/routes/lots.py:189-192
- §3.3 — insert — ambiguity — certification acts on the lot only while it is in QUARANTINE; certifying a test whose lot already left quarantine (sibling assay certified first) marks the test CERTIFIED but leaves the lot untouched — implementation/routes/lots.py:269-284
- §3.3 — revise — mismatch — final_viability_pct reflects the most recently certified assay *that acted on the lot* (certified while the lot sat in QUARANTINE), not any certified assay — implementation/routes/lots.py:270-273
- §3.4 — insert — ambiguity — packing requires the caller's X-User-ID to resolve to an existing volunteer (ERR_NOT_FOUND) that is ACTIVE (ERR_INVALID_STATE) — implementation/routes/lots.py:332-337
- §3.4 — insert — ambiguity — a RECALLED packet is never moved by later checkout-side transitions; return/verify/write-off act only on packets in CHECKED_OUT or RETURNED, leaving recalled packets and their in-packets seeds intact — implementation/routes/checkouts.py:150, 173, 241
- §3.5 — insert — ambiguity — a Member attempting to open a dispute from RETURNED is refused with ERR_INVALID_STATE — implementation/routes/checkouts.py:201-204
- §3.5 — insert — ambiguity — the optional dispute reason is accepted but not persisted on the checkout record — implementation/routes/checkouts.py:198
- §3.6 — revise — mismatch — intake submission against a terminal event draws ERR_ALREADY_TERMINAL, not ERR_EVENT_NOT_INTAKE_OPEN — implementation/routes/intake_items.py:57-59, 90-91
- §3.6 — revise — mismatch — credit redemption against a terminal event draws ERR_ALREADY_TERMINAL, not ERR_EVENT_NOT_INTAKE_OPEN — implementation/routes/swap_events.py:269-271, 284-285

Everything else in the implementation (endpoint set, role lists, state machines, all calculation formulas, ceiling rules, cascade hops, envelope shapes, rounding rules) was already uniquely pinned by the PRD and required no change.
