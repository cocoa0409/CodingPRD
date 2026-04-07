import {
    apiClient,
    buildUserHeaders,
    handleApiResponse,
    validateErrorEnvelope, createContractPayload,
    createEventPayload,
    createShiftPayload,
    createStaffProfilePayload,
    createAssignmentPayload,
    createConflictPairingPayload,
    addHours,
    StaffingContract,
    Event,
    Shift,
    StaffProfile,
    Assignment,
    ContractStatus,
    EventStatus,
    ShiftStatus,
    AssignmentStatus,
    UserRole, ApiErrorId,
    createAndActivateContract
} from '../../../test-helpers';

describe('Phase 3: Business Logic Unit Tests', () => {
    const coordinatorHeaders = buildUserHeaders('coordinator-1', UserRole.StaffingCoordinator);
    const staffMemberHeaders = buildUserHeaders('staff-1', UserRole.StaffMember);
    const accountManagerHeaders = buildUserHeaders('manager-1', UserRole.AccountManager);
    describe('Rule: cancel-assignment', () => {
        describe('P3-CANCEL-ASSIGN-01.1: Cancel confirmed assignment', () => {
            it('should reopen shift and downgrade ready event when cancelling confirmed assignment', async () => {
                const contract = await createAndActivateContract();
                const eventRes = await apiClient.createEvent(
                    contract.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                const event = handleApiResponse<Event>(eventRes, 201);

                const shiftRes = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload(),
                    coordinatorHeaders
                );
                const shift = handleApiResponse<Shift>(shiftRes, 201);

                const staffRes = await apiClient.createStaffProfile(
                    contract.id,
                    createStaffProfilePayload(),
                    coordinatorHeaders
                );
                const staff = handleApiResponse<StaffProfile>(staffRes, 201);

                const assignRes = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift.id, staff.id),
                    accountManagerHeaders
                );
                const assignment = handleApiResponse<Assignment>(assignRes, 201);
                await apiClient.acceptAssignment(contract.id, assignment.id, staffMemberHeaders);
                await apiClient.confirmAssignment(contract.id, assignment.id, coordinatorHeaders);

                await apiClient.updateEventStatus(
                    contract.id,
                    event.id,
                    { status: EventStatus.READY_FOR_EXECUTION },
                    coordinatorHeaders
                );

                const cancelRes = await apiClient.cancelAssignment(contract.id, assignment.id, coordinatorHeaders);
                const cancelledAssignment = handleApiResponse<Assignment>(cancelRes, 200);

                expect(cancelledAssignment.status).toBe(AssignmentStatus.CANCELLED);

                const shiftCheckRes = await apiClient.getShift(contract.id, event.id, shift.id, coordinatorHeaders);
                const reopenedShift = handleApiResponse<Shift>(shiftCheckRes, 200);
                expect(reopenedShift.status).toBe(ShiftStatus.OPEN);

                const eventCheckRes = await apiClient.getEvent(contract.id, event.id, coordinatorHeaders);
                const downgradedEvent = handleApiResponse<Event>(eventCheckRes, 200);
                expect(downgradedEvent.status).toBe(EventStatus.PLANNING);
            });
        });

        describe('P3-CANCEL-ASSIGN-01.2: Cancel accepted assignment', () => {
            it('should reopen shift when cancelling an ACCEPTED assignment', async () => {
                const contract = await createAndActivateContract();
                const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders).then(r => handleApiResponse<Event>(r, 201));
                const shift = await apiClient.createShift(contract.id, event.id, createShiftPayload(), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));
                const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));
                const assignment = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift.id, staff.id), accountManagerHeaders).then(r => handleApiResponse<Assignment>(r, 201));

                await apiClient.acceptAssignment(contract.id, assignment.id, staffMemberHeaders);

                const cancelRes = await apiClient.cancelAssignment(contract.id, assignment.id, coordinatorHeaders);
                const cancelledAssignment = handleApiResponse<Assignment>(cancelRes, 200);

                expect(cancelledAssignment.status).toBe(AssignmentStatus.CANCELLED);
                const shiftCheckRes = await apiClient.getShift(contract.id, event.id, shift.id, coordinatorHeaders);
                const reopenedShift = handleApiResponse<Shift>(shiftCheckRes, 200);
                expect(reopenedShift.status).toBe(ShiftStatus.OPEN);

                const eventCheckRes = await apiClient.getEvent(contract.id, event.id, coordinatorHeaders);
                const downgradedEvent = handleApiResponse<Event>(eventCheckRes, 200);
                expect(downgradedEvent.status).toBe(EventStatus.PLANNING);
            });
        });

        describe('P3-CANCEL-ASSIGN-01.3: Cancel proposed assignment', () => {
            it('should not downgrade planning event when cancelling proposed assignment', async () => {
                const contract = await createAndActivateContract();
                const eventRes = await apiClient.createEvent(
                    contract.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                const event = handleApiResponse<Event>(eventRes, 201);

                const shift1Res = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({ role_name: 'Shift 1' }),
                    coordinatorHeaders
                );
                const shift1 = handleApiResponse<Shift>(shift1Res, 201);

                const shift2Res = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({ role_name: 'Shift 2' }),
                    coordinatorHeaders
                );
                const shift2 = handleApiResponse<Shift>(shift2Res, 201);

                const staffRes = await apiClient.createStaffProfile(
                    contract.id,
                    createStaffProfilePayload(),
                    coordinatorHeaders
                );
                const staff = handleApiResponse<StaffProfile>(staffRes, 201);

                const assignRes = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift1.id, staff.id),
                    accountManagerHeaders
                );
                const assignment = handleApiResponse<Assignment>(assignRes, 201);

                const cancelRes = await apiClient.cancelAssignment(contract.id, assignment.id, coordinatorHeaders);
                handleApiResponse<Assignment>(cancelRes, 200);

                const eventCheckRes = await apiClient.getEvent(contract.id, event.id, coordinatorHeaders);
                const unchangedEvent = handleApiResponse<Event>(eventCheckRes, 200);
                expect(unchangedEvent.status).toBe(EventStatus.PLANNING);
            });
        });

        describe('P3-CANCEL-ASSIGN-01.4: Cancel assignment with override penalty', () => {
            it('should subtract both OT and override penalties from ledger', async () => {
                const contract = await createAndActivateContract(10000.00);
                const eventRes = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders);
                const event = handleApiResponse<Event>(eventRes, 201);
                for (let i = 0; i < 3; i++) {
                    const otherStaffRes = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ first_name: `OTStaff${i}` }), coordinatorHeaders);
                    const otherStaff = handleApiResponse<StaffProfile>(otherStaffRes, 201);
                    const otShiftRes = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: 1700000000 + (i * 150000), end_time: 1700000000 + (i * 150000) + 147600 }), coordinatorHeaders);
                    const otShift = handleApiResponse<Shift>(otShiftRes, 201);
                    const otAssignRes = await apiClient.createAssignment(contract.id, createAssignmentPayload(otShift.id, otherStaff.id), accountManagerHeaders);
                    const otAssign = handleApiResponse<Assignment>(otAssignRes, 201);
                    await apiClient.acceptAssignment(contract.id, otAssign.id, staffMemberHeaders);
                    await apiClient.confirmAssignment(contract.id, otAssign.id, coordinatorHeaders);
                }
                const staffRes = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }), coordinatorHeaders);
                const staff = handleApiResponse<StaffProfile>(staffRes, 201);
                const shift40Res = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: 1700500000, end_time: 1700644000 }), coordinatorHeaders);
                const shift40 = handleApiResponse<Shift>(shift40Res, 201);
                const assign40Res = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift40.id, staff.id), accountManagerHeaders);
                const assign40 = handleApiResponse<Assignment>(assign40Res, 201);
                await apiClient.acceptAssignment(contract.id, assign40.id, staffMemberHeaders);
                await apiClient.confirmAssignment(contract.id, assign40.id, coordinatorHeaders);
                const newShiftRes = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: 1700700000, end_time: 1700703600 }), coordinatorHeaders);
                const newShift = handleApiResponse<Shift>(newShiftRes, 201);
                const res = await apiClient.createAssignment(contract.id, createAssignmentPayload(newShift.id, staff.id, { override_risk_check: true }), accountManagerHeaders);
                const assignmentToCancel = handleApiResponse<Assignment>(res, 201);

                const contractBeforeCancelRes = await apiClient.getContract(contract.id, coordinatorHeaders);
                const contractBeforeCancel = handleApiResponse<StaffingContract>(contractBeforeCancelRes, 200);
                expect(contractBeforeCancel.compliance_risk_score).toBe(30);

                await apiClient.cancelAssignment(contract.id, assignmentToCancel.id, coordinatorHeaders);

                const contractAfterCancelRes = await apiClient.getContract(contract.id, coordinatorHeaders);
                const contractAfterCancel = handleApiResponse<StaffingContract>(contractAfterCancelRes, 200);
                expect(contractAfterCancel.compliance_risk_score).toBe(15);
            });
        });

        describe('P3-CANCEL-ASSIGN-01.5: Cancel OT assignment reverts ledgers (TCB-02)', () => {
            it('should revert budget and risk score when cancelling a confirmed OT assignment', async () => {
                const contract = await createAndActivateContract(5000.00);
                const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders).then(r => handleApiResponse<Event>(r, 201));
                const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));

                const shift = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: 1700000000, end_time: 1700000000 + (41 * 3600) }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));

                const assignRes = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift.id, staff.id), accountManagerHeaders);
                const assignment = handleApiResponse<Assignment>(assignRes, 201);
                await apiClient.acceptAssignment(contract.id, assignment.id, staffMemberHeaders);
                await apiClient.confirmAssignment(contract.id, assignment.id, coordinatorHeaders);

                const contractBeforeCancel = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));
                const budgetBeforeCancel = contractBeforeCancel.budget_balance;

                expect(contractBeforeCancel.compliance_risk_score).toBe(5);

                await apiClient.cancelAssignment(contract.id, assignment.id, coordinatorHeaders);

                const contractAfterCancel = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));

                expect(contractAfterCancel.budget_balance).toBeCloseTo(budgetBeforeCancel + assignment.provisional_cost);

                expect(contractAfterCancel.compliance_risk_score).toBe(0);
            });
        });

        describe('P3-CANCEL-ASSIGN-01.6: Cancel non-OT assignment does not affect risk score (TCB-2-08)', () => {
            it('should not change compliance risk score when a non-overtime assignment is cancelled', async () => {
                const contract = await createAndActivateContract(10000.00);
                const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders).then(r => handleApiResponse<Event>(r, 201));
                const staffOT = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ first_name: 'OT', base_pay_rate_per_hour: 20.00 }), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));
                const staffRegular = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ first_name: 'Regular', base_pay_rate_per_hour: 20.00 }), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));

                const otShift = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: 1700000000, end_time: 1700000000 + (41 * 3600) }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));
                const otAssign = await apiClient.createAssignment(contract.id, createAssignmentPayload(otShift.id, staffOT.id), accountManagerHeaders).then(r => handleApiResponse<Assignment>(r, 201));
                await apiClient.acceptAssignment(contract.id, otAssign.id, staffMemberHeaders);
                await apiClient.confirmAssignment(contract.id, otAssign.id, coordinatorHeaders);

                const regularShift = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: 1700100000, end_time: 1700100000 + (8 * 3600) }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));
                const regularAssign = await apiClient.createAssignment(contract.id, createAssignmentPayload(regularShift.id, staffRegular.id), accountManagerHeaders).then(r => handleApiResponse<Assignment>(r, 201));
                await apiClient.acceptAssignment(contract.id, regularAssign.id, staffMemberHeaders);
                await apiClient.confirmAssignment(contract.id, regularAssign.id, coordinatorHeaders);

                const contractBeforeCancel = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));
                expect(contractBeforeCancel.compliance_risk_score).toBe(5);

                await apiClient.cancelAssignment(contract.id, regularAssign.id, coordinatorHeaders);

                const contractAfterCancel = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));

                expect(contractAfterCancel.compliance_risk_score).toBe(5);
            });
        });
    });

    describe('Rule: initiate-payroll-rule', () => {
        describe('P3-INIT-PAYROLL-01.1: Initiate payroll with all resolved assignments', () => {
            it('should allow payroll initiation when all assignments resolved', async () => {
                const contract = await createAndActivateContract();
                const eventRes = await apiClient.createEvent(
                    contract.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                const event = handleApiResponse<Event>(eventRes, 201);

                const shift1Res = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({ role_name: 'Shift 1' }),
                    coordinatorHeaders
                );
                const shift1 = handleApiResponse<Shift>(shift1Res, 201);

                const shift2Start = addHours(shift1.end_time, 9);
                const shift2Res = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({
                        role_name: 'Shift 2',
                        start_time: shift2Start,
                        end_time: addHours(shift2Start, 8),
                    }),
                    coordinatorHeaders
                );
                const shift2 = handleApiResponse<Shift>(shift2Res, 201);

                const shift3Start = addHours(shift2.end_time, 9);
                const shift3Res = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({
                        role_name: 'Shift 3',
                        start_time: shift3Start,
                        end_time: addHours(shift3Start, 8),
                    }),
                    coordinatorHeaders
                );
                const shift3 = handleApiResponse<Shift>(shift3Res, 201);

                const staffRes = await apiClient.createStaffProfile(
                    contract.id,
                    createStaffProfilePayload(),
                    coordinatorHeaders
                );
                const staff = handleApiResponse<StaffProfile>(staffRes, 201);

                const assign1Res = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift1.id, staff.id),
                    accountManagerHeaders
                );
                const assign1 = handleApiResponse<Assignment>(assign1Res, 201);
                await apiClient.acceptAssignment(contract.id, assign1.id, staffMemberHeaders);
                await apiClient.confirmAssignment(contract.id, assign1.id, coordinatorHeaders);

                const assign2Res = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift2.id, staff.id),
                    accountManagerHeaders
                );
                const assign2 = handleApiResponse<Assignment>(assign2Res, 201);
                await apiClient.declineAssignment(contract.id, assign2.id, staffMemberHeaders);

                const assign3Res = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift3.id, staff.id),
                    accountManagerHeaders
                );
                const assign3 = handleApiResponse<Assignment>(assign3Res, 201);
                await apiClient.cancelAssignment(contract.id, assign3.id, coordinatorHeaders);

                const payrollRes = await apiClient.initiatePayroll(contract.id, coordinatorHeaders);
                const payrollContract = handleApiResponse<StaffingContract>(payrollRes, 200);

                expect(payrollContract.status).toBe(ContractStatus.PAYROLL_PENDING);
            });
        });

        describe('P3-INIT-PAYROLL-01.2: Cannot initiate with unresolved assignments', () => {
            it('should reject payroll initiation if assignment still ACCEPTED', async () => {
                const contract = await createAndActivateContract();
                const eventRes = await apiClient.createEvent(
                    contract.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                const event = handleApiResponse<Event>(eventRes, 201);

                const shiftRes = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload(),
                    coordinatorHeaders
                );
                const shift = handleApiResponse<Shift>(shiftRes, 201);

                const staffRes = await apiClient.createStaffProfile(
                    contract.id,
                    createStaffProfilePayload(),
                    coordinatorHeaders
                );
                const staff = handleApiResponse<StaffProfile>(staffRes, 201);

                const assignRes = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift.id, staff.id),
                    accountManagerHeaders
                );
                const assignment = handleApiResponse<Assignment>(assignRes, 201);
                await apiClient.acceptAssignment(contract.id, assignment.id, staffMemberHeaders);

                const res = await apiClient.initiatePayroll(contract.id, coordinatorHeaders);

                validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_UNRESOLVED_ASSIGNMENTS_EXIST });
            });
        });

        describe('P3-INIT-PAYROLL-01.3: Contract not active for payroll', () => {
            it('should reject payroll initiation if contract is not ACTIVE', async () => {
                const contractRes = await apiClient.createContract(createContractPayload(), coordinatorHeaders);
                const contract = handleApiResponse<StaffingContract>(contractRes, 201);

                const res = await apiClient.initiatePayroll(contract.id, coordinatorHeaders);

                validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_ACTIVE });
            });
        });
    });

    describe('Rule: finalize-payroll-atomic-rule', () => {
        describe('P3-FINALIZE-PAYROLL-01.1: Clear provisional debits on success', () => {
            it('should zero out provisional_debits after successful finalization', async () => {
                const contract = await createAndActivateContract(1000.00);
                const eventRes = await apiClient.createEvent(
                    contract.id,
                    createEventPayload(),
                    coordinatorHeaders
                );
                const event = handleApiResponse<Event>(eventRes, 201);

                const staffRes = await apiClient.createStaffProfile(
                    contract.id,
                    createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }),
                    coordinatorHeaders
                );
                const staff = handleApiResponse<StaffProfile>(staffRes, 201);

                const shiftRes = await apiClient.createShift(
                    contract.id,
                    event.id,
                    createShiftPayload({
                        start_time: 1700000000,
                        end_time: 1700036000,
                    }),
                    coordinatorHeaders
                );
                const shift = handleApiResponse<Shift>(shiftRes, 201);

                const assignRes = await apiClient.createAssignment(
                    contract.id,
                    createAssignmentPayload(shift.id, staff.id),
                    accountManagerHeaders
                );
                const assignment = handleApiResponse<Assignment>(assignRes, 201);
                await apiClient.acceptAssignment(contract.id, assignment.id, staffMemberHeaders);
                await apiClient.confirmAssignment(contract.id, assignment.id, coordinatorHeaders);

                await apiClient.initiatePayroll(contract.id, coordinatorHeaders);

                const finalizeRes = await apiClient.finalizePayroll(contract.id, coordinatorHeaders);
                const finalContract = handleApiResponse<StaffingContract>(finalizeRes, 200);

                expect(finalContract.status).toBe(ContractStatus.CLOSED);

                expect(finalContract.budget_balance).toBe(800.00);

                const paidAssignmentRes = await apiClient.getAssignment(contract.id, assignment.id, coordinatorHeaders);
                const paidAssignment = handleApiResponse<Assignment>(paidAssignmentRes, 200);
                expect(paidAssignment.status).toBe(AssignmentStatus.PAID);
                expect(paidAssignment.final_payout).toBe(200.00);
            });
        });

        describe('P3-FINALIZE-PAYROLL-01.3: Risk score reconciliation (penalty removal)', () => {
            it('should remove risk penalty if assignment ceases to be OT during finalization', async () => {
                const contract = await createAndActivateContract(2000.00);
                const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders).then(r => handleApiResponse<Event>(r, 201));
                const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));

                const shiftA = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: 1700000000, end_time: 1700140400 }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));
                const assignA = await apiClient.createAssignment(contract.id, createAssignmentPayload(shiftA.id, staff.id), accountManagerHeaders).then(r => handleApiResponse<Assignment>(r, 201));
                await apiClient.acceptAssignment(contract.id, assignA.id, staffMemberHeaders);
                await apiClient.confirmAssignment(contract.id, assignA.id, coordinatorHeaders);

                const shiftB = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: 1700169200, end_time: 1700176400 }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));
                const assignB = await apiClient.createAssignment(contract.id, createAssignmentPayload(shiftB.id, staff.id), accountManagerHeaders).then(r => handleApiResponse<Assignment>(r, 201));
                await apiClient.acceptAssignment(contract.id, assignB.id, staffMemberHeaders);
                await apiClient.confirmAssignment(contract.id, assignB.id, coordinatorHeaders);

                let contractMid = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));
                expect(contractMid.compliance_risk_score).toBe(5);

                await apiClient.cancelAssignment(contract.id, assignA.id, coordinatorHeaders);

                contractMid = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));
                expect(contractMid.compliance_risk_score).toBe(5);

                await apiClient.initiatePayroll(contract.id, coordinatorHeaders);
                await apiClient.finalizePayroll(contract.id, coordinatorHeaders);

                const finalContract = await apiClient.getContract(contract.id, coordinatorHeaders).then(r => handleApiResponse<StaffingContract>(r, 200));
                expect(finalContract.compliance_risk_score).toBe(0);
            });
        });

        describe('P3-FINALIZE-PAYROLL-01.4: Contract not ready for payroll', () => {
            it('should reject finalization if contract is not PAYROLL_PENDING', async () => {
                const contract = await createAndActivateContract();
                const res = await apiClient.finalizePayroll(contract.id, coordinatorHeaders);

                validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_READY_FOR_PAYROLL });
            });
        });
    });

    describe('Extra Tests for Coverage', () => {
        it('should allow assignment if rest period is exactly 8 hours', async () => {
            const contract = await createAndActivateContract();
            const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders).then(r => handleApiResponse<Event>(r, 201));
            const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload(), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));

            const shift1EndTime = 1700028800;
            const shift1 = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: 1700000000, end_time: shift1EndTime }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));
            const assign1 = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift1.id, staff.id), accountManagerHeaders).then(r => handleApiResponse<Assignment>(r, 201));
            await apiClient.acceptAssignment(contract.id, assign1.id, staffMemberHeaders);
            await apiClient.confirmAssignment(contract.id, assign1.id, coordinatorHeaders);

            const shift2StartTime = shift1EndTime + (8 * 3600);
            const shift2 = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: shift2StartTime, end_time: shift2StartTime + 3600 }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));

            const res = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift2.id, staff.id), accountManagerHeaders);
            expect(res.status).toBe(201);
        });

        it('should reject assignment creation with override if budget is insufficient', async () => {
            const contract = await createAndActivateContract(100.00);
            const event = await apiClient.createEvent(contract.id, createEventPayload(), coordinatorHeaders).then(r => handleApiResponse<Event>(r, 201));
            const staff = await apiClient.createStaffProfile(contract.id, createStaffProfilePayload({ base_pay_rate_per_hour: 20.00 }), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));
            const shift = await apiClient.createShift(contract.id, event.id, createShiftPayload({ start_time: 1700000000, end_time: 1700021600 }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));

            const res = await apiClient.createAssignment(contract.id, createAssignmentPayload(shift.id, staff.id, { override_risk_check: true }), accountManagerHeaders);
            validateErrorEnvelope(res, { expectedErrorId: ApiErrorId.ERR_INSUFFICIENT_BUDGET });
        });
    });

    describe('Rule: create-conflict-pairing-rule & check-interpersonal-conflict', () => {
        describe('P3-CONFLICT-01.1: Conflict pairings are scoped to a contract (TCB-06)', () => {
            it('should allow assignment in one contract even if a conflict exists in another', async () => {
                const contractA = await createAndActivateContract();
                const contractB = await createAndActivateContract();

                const staffA1 = await apiClient.createStaffProfile(contractA.id, createStaffProfilePayload({ first_name: 'Jane' }), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));
                const staffA2 = await apiClient.createStaffProfile(contractA.id, createStaffProfilePayload({ first_name: 'John' }), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));

                await apiClient.createConflictPairing(contractA.id, createConflictPairingPayload(staffA1.id, staffA2.id), coordinatorHeaders);

                const staffB1 = await apiClient.createStaffProfile(contractB.id, createStaffProfilePayload({ first_name: 'Jane' }), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));
                const staffB2 = await apiClient.createStaffProfile(contractB.id, createStaffProfilePayload({ first_name: 'John' }), coordinatorHeaders).then(r => handleApiResponse<StaffProfile>(r, 201));

                const eventB = await apiClient.createEvent(contractB.id, createEventPayload(), coordinatorHeaders).then(r => handleApiResponse<Event>(r, 201));
                const shiftB1 = await apiClient.createShift(contractB.id, eventB.id, createShiftPayload({ role_name: 'Role 1' }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));
                const shiftB2 = await apiClient.createShift(contractB.id, eventB.id, createShiftPayload({ role_name: 'Role 2' }), coordinatorHeaders).then(r => handleApiResponse<Shift>(r, 201));

                const assignB1 = await apiClient.createAssignment(contractB.id, createAssignmentPayload(shiftB1.id, staffB1.id), accountManagerHeaders).then(r => handleApiResponse<Assignment>(r, 201));
                await apiClient.acceptAssignment(contractB.id, assignB1.id, staffMemberHeaders);
                await apiClient.confirmAssignment(contractB.id, assignB1.id, coordinatorHeaders);

                const res = await apiClient.createAssignment(contractB.id, createAssignmentPayload(shiftB2.id, staffB2.id), accountManagerHeaders);

                const assignmentB2 = handleApiResponse<Assignment>(res, 201);
                expect(assignmentB2.status).toBe(AssignmentStatus.PROPOSED);
            });
        });
    });
});
