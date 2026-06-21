# Step 8 Summary — task_0078_espp_stock_purchase

## Important context: the prompt's `<step_7_diff>` is boilerplate, not this task's diff
The `<step_7_diff>` block in the Step-8 prompt (730/365-day holding thresholds,
`contribution_rate` rename, `refunded`/`disqualified` side-effect fields,
min-of-FMV lookback, annual-cap "per-period→annual" rename, no-seed removal,
19 deleted tests, etc.) does NOT correspond to this task. The actual Step-7
record for task_0078 is `workspace/STEP7_SUMMARY.md`, which reports:
- 0 tests deleted (all 70 pass across 8 parallel rounds).
- 2 test-only fixes that are pure test-code bugs (a missing `admin_headers`
  fixture param; a test that POSTed a Form 3922 expecting 201 when PRD §3.5
  already creates the form during run-purchase). Neither reveals PRD silence.
- 1 implementation fix: `new_id()` `uuid.uuid4().hex` → `str(uuid.uuid4())`,
  already uniquely determined by PRD §2.4 ("a UUID with no type prefix"), so it
  needs no PRD pin.

Because the boilerplate diff does not apply, I rebuilt the analysis directly from
`workspace/implementation/app.py` (read in full, 1354 lines) versus
`workspace/PRD.md` (read in full, 238 lines), per the Method's instruction to
align PRD_FINALIZED.md to what the implementation actually does.

## File deltas
- PRD.md: 238 lines. PRD_FINALIZED.md: 238 lines (the §3.3 enrollment sentence is
  widened in place on its single physical line; no line added/removed).
- Line-count delta: 0 lines (+0.0%). Character delta: ~+180 chars (one inserted
  clause within line 117).

## Changes (one bullet per edit)
1. §3.3 The Employee's Contribution Lifecycle — insert+revise — added the
   offering-must-be-`OPEN` enrollment gate as the LAST step of the enrollment
   validation order, after the duplicate-enrollment check, rejecting with
   `ERR_INVALID_STATE` (HTTP 409); changed the preceding "and finally" on the
   duplicate clause to "then" so ordering reads correctly. — impl:
   app.py:897-905 (duplicate check at 897-902 precedes `if offering["status"] !=
   "OPEN": ERR_INVALID_STATE` at 904-905).

## Why this is the only edit
This is the one place where the implementation pins a behavioral choice that
PRD.md leaves open. PRD §3.2 says only "once closed no new enrollment may be
created" — it never gives the error code, the HTTP status, the full set of
non-OPEN offering states it applies to, or its position in the §3.3 validation
order (which the PRD otherwise enumerates exhaustively and ends at
ERR_DUPLICATE_ENROLLMENT). The impl rejects any non-OPEN offering with
ERR_INVALID_STATE/409 and evaluates it AFTER the duplicate check. Pinned.

Everything else the implementation does is already determined verbatim by PRD.md.
Confirmed against the full source:
- Pricing (lookback = lower of grant/purchase FMV when enabled, else purchase
  FMV; price = applicable_fmv*(100-discount)/100 half-up) — PRD §3.5 = app.py:767-772.
- $25,000 annual cap (per participant per calendar year; year = year of
  purchase_date; grant-date-FMV basis; remaining_capacity floored at 0;
  cap-permitted = remaining//grant_fmv, cash-permitted = accumulated//price,
  shares = min) — PRD §3.6 = app.py:774-828, ledger 858-868.
- Disposition classification (sale_date ≥ 2nd anniversary of grant_date AND ≥ 1st
  anniversary of purchase_date, inclusive `>=`, via calendar-date anniversaries
  using add_years — NOT 730/365 day counts) — PRD §3.8 = app.py:1254-1256,
  add_years 155-159.
- Disposition tax (qualifying = min(actual gain≥0, statutory discount≥0);
  disqualifying = spread-at-purchase≥0; adjusted basis = cost + ordinary;
  capital gain = proceeds − basis) — PRD §3.8 = app.py:1258-1269. All-integer
  cents, no rounding (PRD §2.5).
- Contribution amount = floor(gross*rate/100) — PRD §3.3 = app.py:1028.
- Form 3922 box3..box6, tax_year = year of purchase_date, issued_by = certifier
  on run / acting officer on demand — PRD §3.5 = app.py:830-838, 1122-1129.
- Cancel-offering / auto-close cascades (enrollments WITHDRAWN + refund POSTED
  contributions, non-terminal batches CANCELLED; ENROLLED→COMPLETED on close;
  offering ENROLLMENT_CLOSED→ACTIVE on first open; ACTIVE→CLOSED when all batches
  terminal and ≥1 PURCHASED) — PRD §3.7 / §3.2 = app.py:602-625, 707-712, 840-853.
- Withdraw refund (POSTED→REFUNDED, refunded_contribution_cents += sum,
  accumulated reset to 0) — PRD §3.3 = app.py:996-1005.
- Serializers expose exactly the PRD-named fields; Contribution carries only
  id+created_at (no version/updated_at), every other resource carries
  created_at/updated_at/version — PRD §2.4 = ser_* 293-405, create_contribution
  1030-1034 (no common_init / no touch on the contribution itself).
- run-purchase guards: required+int expected_version → ERR_NOT_CERTIFIED →
  ERR_STALE_VERSION → ERR_SEGREGATION_OF_DUTIES — PRD §3.5/§2.8/§2.9 =
  app.py:748-762.

## Items considered and intentionally NOT pinned
- `new_id()` UUID format: already pinned by PRD §2.4. No edit.
- Pagination clamping (limit<1→1, >100→100, offset<0→0; get_pagination
  app.py:258-275): PRD §2.3 already gives the 1/100 bounds and defaults; clamp-vs-
  reject is a soft silence whose observable result stays within the stated bounds.
  Pinning it would exceed scope and risk a new mismatch; left as-is.
- run-purchase int-validation of expected_version placed before ERR_NOT_CERTIFIED
  (app.py:748-752): PRD §3.9 places ERR_VALIDATION lowest among body validations,
  but this is a missing-required-field/type check; consistent with PRD, no pin.
- Sort tiebreak `(created_at, id)` (app.py:285-286): ids are random UUIDs so the
  tiebreak is unobservable; PRD §2.3 (created_at ascending) suffices. No pin.
- `if price_per_share > 0` guard in run-purchase (app.py:790): dead branch —
  discount ≤ 15 and FMV > 0 force price > 0. Not observable; no pin.
- not-certified vs stale-version precedence on run-purchase: PRD §3.5 enumerates
  both guards without committing order; the impl checks NOT_CERTIFIED first
  (app.py:754-758). The test suite explicitly accepts either id
  (test_05 validate_error_is_one_of), confirming this is an accepted silence, not
  a pinned behavior. Pinning a strict order could over-constrain a fresh
  implementer beyond what tests require; left as-is.

## Per-edit pre-edit search log

### Edit 1 — enrollment offering-state gate
(a) Subject identified: the precondition that a new enrollment may only be created
    against an offering whose status is OPEN; its error id (ERR_INVALID_STATE),
    HTTP status (409), the offering states it rejects (all non-OPEN), and its
    position in the §3.3 enrollment validation order.
(b) Impl paths enumerated and read:
    - create_enrollment (app.py:873-915): sole enrollment-creation path. Guard
      order: ownership uid==participant_id (883-884) → participant 404 (886) →
      offering 404 (887) → ERR_FIVE_PERCENT_OWNER (890-891) →
      ERR_PARTICIPANT_NOT_ACTIVE (892-893) → ERR_RATE_EXCEEDS_LIMIT (894-896) →
      ERR_DUPLICATE_ENROLLMENT (897-902) → `if offering["status"] != "OPEN":
      ERR_INVALID_STATE` (904-905). Confirms the gate is LAST (after duplicate)
      and uses ERR_INVALID_STATE/409 for ANY non-OPEN status.
    - close_enrollment (app.py:590-599): OPEN→ENROLLMENT_CLOSED; PRD §3.2 already
      says "once closed no new enrollment may be created." My wording ("only an
      OPEN offering accepts a new enrollment") is consistent and strictly more
      precise; it does not contradict §3.2.
    - cancel_offering (602-625): moves offering to CANCELLED — also non-OPEN, so
      enrollment is correctly barred; my "any non-OPEN" wording covers it.
    - suspend/resume (955-981): transitions on an EXISTING enrollment, not new
      enrollment; scoping the clause to "a new enrollment" leaves them untouched.
    - No other route creates an Enrollment (only `@app.post("/enrollments")`).
    - ERR_INVALID_STATE/409 already exists in PRD §5 error catalogue.
(c) Wording adjustment: placed the new clause as the final ("and finally")
    enrollment guard, immediately after the duplicate clause (downgraded from
    "and finally" to "then"), matching the impl's evaluation order exactly. Used
    "an offering whose status is not OPEN" / "only an OPEN offering accepts a new
    enrollment" to cover all non-OPEN states (ENROLLMENT_CLOSED, ACTIVE, CLOSED,
    CANCELLED) without enumerating them, so no off-site offering state is
    mis-described.
