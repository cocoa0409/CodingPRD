import {
    apiClient,
    buildUserHeaders,
    getSuccessData,
    handleApiResponse,
    validateErrorEnvelope,
    assertStaffingContract,
    assertEvent, createContractPayload,
    createEventPayload,
    createShiftPayload,
    createStaffProfilePayload,
    createAssignmentPayload,
    StaffingContract,
    Event,
    Shift,
    StaffProfile,
    Assignment,
    ContractStatus,
    EventStatus,
    ShiftStatus,
    AssignmentStatus,
    UserRole, ApiErrorId
} from '../../../test-helpers';

describe('Phase 2: State Machine Transitions', () => {
    const coordinatorHeaders = buildUserHeaders('coordinator-1', UserRole.StaffingCoordinator);
    const staffMemberHeaders = buildUserHeaders('staff-1', UserRole.StaffMember);
    const accountManagerHeaders = buildUserHeaders('manager-1', UserRole.AccountManager);

    describe('StaffingContract State Machine', () => {
        describe('Transition: activate (PLANNING -> ACTIVE)', () => {
            describe('P2-CONTRACT-01.1: Contract in PLANNING successfully transitions to ACTIVE', () => {
                it('should transition contract from PLANNING to ACTIVE upon activation', async () => {
                    const contractRes = await apiClient.createContract(
                        createContractPayload({ client_name: 'Test Contract' }),
                        coordinatorHeaders
                    );
                    const contract = getSuccessData<StaffingContract>(contractRes);
                    expect(contract.status).toBe(ContractStatus.PLANNING);

                    const activateRes = await apiClient.activateContract(contract.id, coordinatorHeaders);
                    const activatedContract = handleApiResponse<StaffingContract>(activateRes, 200);

                    assertStaffingContract(activatedContract);
                    expect(activatedContract.status).toBe(ContractStatus.ACTIVE);

                    const getRes = await apiClient.getContract(contract.id, coordinatorHeaders);
                    const retrievedContract = handleApiResponse<StaffingContract>(getRes, 200);
                    expect(retrievedContract.status).toBe(ContractStatus.ACTIVE);
                });
            });

            describe('P2-CONTRACT-01.2: Activating already ACTIVE contract fails', () => {
                it('should fail with conflict error when activating an already active contract', async () => {
                    const contractRes = await apiClient.createContract(
                        createContractPayload({ client_name: 'Already Active Contract' }),
                        coordinatorHeaders
                    );
                    const contract = getSuccessData<StaffingContract>(contractRes);

                    await apiClient.activateContract(contract.id, coordinatorHeaders);

                    const getRes = await apiClient.getContract(contract.id, coordinatorHeaders);
                    const activeContract = handleApiResponse<StaffingContract>(getRes, 200);
                    expect(activeContract.status).toBe(ContractStatus.ACTIVE);

                    const secondActivateRes = await apiClient.activateContract(contract.id, coordinatorHeaders);

                    validateErrorEnvelope(secondActivateRes, {
                        expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_IN_PLANNING
                    });

                    const finalGetRes = await apiClient.getContract(contract.id, coordinatorHeaders);
                    const finalContract = handleApiResponse<StaffingContract>(finalGetRes, 200);
                    expect(finalContract.status).toBe(ContractStatus.ACTIVE);
                });
            });

            describe('P2-CONTRACT-01.3: Activating PAYROLL_PENDING contract fails', () => {
                it('should fail with conflict error when activating a contract in PAYROLL_PENDING state', async () => {
                    const contractRes = await apiClient.createContract(
                        createContractPayload({ client_name: 'Payroll Pending Contract' }),
                        coordinatorHeaders
                    );
                    const contract = getSuccessData<StaffingContract>(contractRes);

                    await apiClient.activateContract(contract.id, coordinatorHeaders);
                    await apiClient.initiatePayroll(contract.id, coordinatorHeaders);

                    const getRes = await apiClient.getContract(contract.id, coordinatorHeaders);
                    const payrollPendingContract = handleApiResponse<StaffingContract>(getRes, 200);
                    expect(payrollPendingContract.status).toBe(ContractStatus.PAYROLL_PENDING);

                    const activateRes = await apiClient.activateContract(contract.id, coordinatorHeaders);

                    validateErrorEnvelope(activateRes, {
                        expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_IN_PLANNING
                    });

                    const finalGetRes = await apiClient.getContract(contract.id, coordinatorHeaders);
                    const finalContract = handleApiResponse<StaffingContract>(finalGetRes, 200);
                    expect(finalContract.status).toBe(ContractStatus.PAYROLL_PENDING);
                });
            });
        });

        describe('Transition: initiate_payroll (ACTIVE -> PAYROLL_PENDING)', () => {
            describe('P2-CONTRACT-02.1: Contract in ACTIVE successfully transitions to PAYROLL_PENDING', () => {
                it('should transition contract from ACTIVE to PAYROLL_PENDING when payroll is initiated', async () => {
                    const contractRes = await apiClient.createContract(
                        createContractPayload({ client_name: 'Payroll Test Contract' }),
                        coordinatorHeaders
                    );
                    const contract = getSuccessData<StaffingContract>(contractRes);

                    const activateRes = await apiClient.activateContract(contract.id, coordinatorHeaders);
                    const activeContract = handleApiResponse<StaffingContract>(activateRes, 200);
                    expect(activeContract.status).toBe(ContractStatus.ACTIVE);

                    const payrollRes = await apiClient.initiatePayroll(contract.id, coordinatorHeaders);
                    const payrollPendingContract = handleApiResponse<StaffingContract>(payrollRes, 200);

                    assertStaffingContract(payrollPendingContract);
                    expect(payrollPendingContract.status).toBe(ContractStatus.PAYROLL_PENDING);

                    const getRes = await apiClient.getContract(contract.id, coordinatorHeaders);
                    const retrievedContract = handleApiResponse<StaffingContract>(getRes, 200);
                    expect(retrievedContract.status).toBe(ContractStatus.PAYROLL_PENDING);
                });
            });

            describe('P2-CONTRACT-02.2: Initiating payroll for PLANNING contract fails', () => {
                it('should fail with conflict error when initiating payroll for a contract in PLANNING state', async () => {
                    const contractRes = await apiClient.createContract(
                        createContractPayload({ client_name: 'Planning Contract' }),
                        coordinatorHeaders
                    );
                    const contract = getSuccessData<StaffingContract>(contractRes);
                    expect(contract.status).toBe(ContractStatus.PLANNING);

                    const payrollRes = await apiClient.initiatePayroll(contract.id, coordinatorHeaders);

                    validateErrorEnvelope(payrollRes, {
                        expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_ACTIVE
                    });

                    const getRes = await apiClient.getContract(contract.id, coordinatorHeaders);
                    const finalContract = handleApiResponse<StaffingContract>(getRes, 200);
                    expect(finalContract.status).toBe(ContractStatus.PLANNING);
                });
            });
        });

        describe('Transition: finalize_payroll (PAYROLL_PENDING -> CLOSED)', () => {
            describe('P2-CONTRACT-03.1: Contract in PAYROLL_PENDING successfully transitions to CLOSED', () => {
                it('should transition contract from PAYROLL_PENDING to CLOSED when payroll is finalized', async () => {
                    const contractRes = await apiClient.createContract(
                        createContractPayload({ client_name: 'Finalize Payroll Contract' }),
                        coordinatorHeaders
                    );
                    const contract = getSuccessData<StaffingContract>(contractRes);

                    await apiClient.activateContract(contract.id, coordinatorHeaders);

                    const payrollRes = await apiClient.initiatePayroll(contract.id, coordinatorHeaders);
                    const payrollPendingContract = handleApiResponse<StaffingContract>(payrollRes, 200);
                    expect(payrollPendingContract.status).toBe(ContractStatus.PAYROLL_PENDING);

                    const finalizeRes = await apiClient.finalizePayroll(contract.id, coordinatorHeaders);
                    const closedContract = handleApiResponse<StaffingContract>(finalizeRes, 200);

                    assertStaffingContract(closedContract);
                    expect(closedContract.status).toBe(ContractStatus.CLOSED);

                    const getRes = await apiClient.getContract(contract.id, coordinatorHeaders);
                    const retrievedContract = handleApiResponse<StaffingContract>(getRes, 200);
                    expect(retrievedContract.status).toBe(ContractStatus.CLOSED);
                });
            });

            describe('P2-CONTRACT-03.2: Finalizing payroll for ACTIVE contract fails', () => {
                it('should fail with conflict error when finalizing payroll for a contract still in ACTIVE state', async () => {
                    const contractRes = await apiClient.createContract(
                        createContractPayload({ client_name: 'Active Contract' }),
                        coordinatorHeaders
                    );
                    const contract = getSuccessData<StaffingContract>(contractRes);

                    const activateRes = await apiClient.activateContract(contract.id, coordinatorHeaders);
                    const activeContract = handleApiResponse<StaffingContract>(activateRes, 200);
                    expect(activeContract.status).toBe(ContractStatus.ACTIVE);

                    const finalizeRes = await apiClient.finalizePayroll(contract.id, coordinatorHeaders);

                    validateErrorEnvelope(finalizeRes, {
                        expectedErrorId: ApiErrorId.ERR_CONTRACT_NOT_READY_FOR_PAYROLL
                    });

                    const getRes = await apiClient.getContract(contract.id, coordinatorHeaders);
                    const finalContract = handleApiResponse<StaffingContract>(getRes, 200);
                    expect(finalContract.status).toBe(ContractStatus.ACTIVE);
                });
            });
        });
    });

    describe('Event State Machine', () => {
        let testContract: StaffingContract;

        beforeEach(async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Event Test Contract' }),
                coordinatorHeaders
            );
            const contract = getSuccessData<StaffingContract>(contractRes);

            const activateRes = await apiClient.activateContract(contract.id, coordinatorHeaders);
            testContract = handleApiResponse<StaffingContract>(activateRes, 200);
        });

        describe('Transition: mark_ready (PLANNING -> READY_FOR_EXECUTION)', () => {
            describe('P2-EVENT-01.1: Event with all shifts FILLED transitions to READY_FOR_EXECUTION', () => {
                it('should transition event from PLANNING to READY_FOR_EXECUTION when all shifts are filled', async () => {
                    const eventRes = await apiClient.createEvent(
                        testContract.id,
                        createEventPayload({ name: 'Ready Event' }),
                        coordinatorHeaders
                    );
                    const event = getSuccessData<Event>(eventRes);
                    expect(event.status).toBe(EventStatus.PLANNING);

                    const shiftRes = await apiClient.createShift(
                        testContract.id,
                        event.id,
                        createShiftPayload({ role_name: 'Bartender' }),
                        coordinatorHeaders
                    );
                    const shift = getSuccessData<Shift>(shiftRes);

                    const staffRes = await apiClient.createStaffProfile(
                        testContract.id,
                        createStaffProfilePayload({ first_name: 'John', last_name: 'Doe' }),
                        coordinatorHeaders
                    );
                    const staff = getSuccessData<StaffProfile>(staffRes);

                    const assignmentRes = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(shift.id, staff.id),
                        accountManagerHeaders
                    );
                    const assignment = getSuccessData<Assignment>(assignmentRes);

                    await apiClient.acceptAssignment(testContract.id, assignment.id, staffMemberHeaders);
                    await apiClient.confirmAssignment(testContract.id, assignment.id, coordinatorHeaders);

                    const filledShiftRes = await apiClient.getShift(testContract.id, event.id, shift.id, coordinatorHeaders);
                    const filledShift = handleApiResponse<Shift>(filledShiftRes, 200);
                    expect(filledShift.status).toBe(ShiftStatus.FILLED);

                    const updateRes = await apiClient.updateEventStatus(
                        testContract.id,
                        event.id,
                        { status: EventStatus.READY_FOR_EXECUTION },
                        coordinatorHeaders
                    );
                    const readyEvent = handleApiResponse<Event>(updateRes, 200);

                    assertEvent(readyEvent);
                    expect(readyEvent.status).toBe(EventStatus.READY_FOR_EXECUTION);

                    const getRes = await apiClient.getEvent(testContract.id, event.id, coordinatorHeaders);
                    const retrievedEvent = handleApiResponse<Event>(getRes, 200);
                    expect(retrievedEvent.status).toBe(EventStatus.READY_FOR_EXECUTION);
                });
            });

            describe('P2-EVENT-01.2: Marking CANCELLED event as ready fails', () => {
                it('should fail with conflict error when marking a cancelled event as ready', async () => {
                    const eventRes = await apiClient.createEvent(
                        testContract.id,
                        createEventPayload({ name: 'Cancelled Event' }),
                        coordinatorHeaders
                    );
                    const event = getSuccessData<Event>(eventRes);

                    const cancelRes = await apiClient.updateEventStatus(
                        testContract.id,
                        event.id,
                        { status: EventStatus.CANCELLED },
                        coordinatorHeaders
                    );
                    const cancelledEvent = handleApiResponse<Event>(cancelRes, 200);
                    expect(cancelledEvent.status).toBe(EventStatus.CANCELLED);

                    const updateRes = await apiClient.updateEventStatus(
                        testContract.id,
                        event.id,
                        { status: EventStatus.READY_FOR_EXECUTION },
                        coordinatorHeaders
                    );

                    validateErrorEnvelope(updateRes, {
                        expectedErrorId: ApiErrorId.ERR_ILLEGAL_EVENT_STATE_TRANSITION
                    });

                    const getRes = await apiClient.getEvent(testContract.id, event.id, coordinatorHeaders);
                    const finalEvent = handleApiResponse<Event>(getRes, 200);
                    expect(finalEvent.status).toBe(EventStatus.CANCELLED);
                });
            });
        });

        describe('Transition: cancel (PLANNING -> CANCELLED)', () => {
            describe('P2-EVENT-02.1: Event in PLANNING successfully transitions to CANCELLED', () => {
                it('should transition event from PLANNING to CANCELLED', async () => {
                    const eventRes = await apiClient.createEvent(
                        testContract.id,
                        createEventPayload({ name: 'To Cancel Event' }),
                        coordinatorHeaders
                    );
                    const event = getSuccessData<Event>(eventRes);
                    expect(event.status).toBe(EventStatus.PLANNING);

                    const updateRes = await apiClient.updateEventStatus(
                        testContract.id,
                        event.id,
                        { status: EventStatus.CANCELLED },
                        coordinatorHeaders
                    );
                    const cancelledEvent = handleApiResponse<Event>(updateRes, 200);

                    assertEvent(cancelledEvent);
                    expect(cancelledEvent.status).toBe(EventStatus.CANCELLED);

                    const getRes = await apiClient.getEvent(testContract.id, event.id, coordinatorHeaders);
                    const retrievedEvent = handleApiResponse<Event>(getRes, 200);
                    expect(retrievedEvent.status).toBe(EventStatus.CANCELLED);
                });
            });

            describe('P2-EVENT-02.2: Cancelling already CANCELLED event fails', () => {
                it('should fail with conflict error when cancelling an already cancelled event', async () => {
                    const eventRes = await apiClient.createEvent(
                        testContract.id,
                        createEventPayload({ name: 'Already Cancelled Event' }),
                        coordinatorHeaders
                    );
                    const event = getSuccessData<Event>(eventRes);

                    await apiClient.updateEventStatus(
                        testContract.id,
                        event.id,
                        { status: EventStatus.CANCELLED },
                        coordinatorHeaders
                    );

                    const getRes = await apiClient.getEvent(testContract.id, event.id, coordinatorHeaders);
                    const cancelledEvent = handleApiResponse<Event>(getRes, 200);
                    expect(cancelledEvent.status).toBe(EventStatus.CANCELLED);

                    const secondCancelRes = await apiClient.updateEventStatus(
                        testContract.id,
                        event.id,
                        { status: EventStatus.CANCELLED },
                        coordinatorHeaders
                    );

                    validateErrorEnvelope(secondCancelRes, {
                        expectedErrorId: ApiErrorId.ERR_ILLEGAL_EVENT_STATE_TRANSITION
                    });

                    const finalGetRes = await apiClient.getEvent(testContract.id, event.id, coordinatorHeaders);
                    const finalEvent = handleApiResponse<Event>(finalGetRes, 200);
                    expect(finalEvent.status).toBe(EventStatus.CANCELLED);
                });
            });
        });

        describe('Transition: cancel (READY_FOR_EXECUTION -> CANCELLED)', () => {
            describe('P2-EVENT-03.1: Event in READY_FOR_EXECUTION successfully transitions to CANCELLED', () => {
                it('should transition event from READY_FOR_EXECUTION to CANCELLED', async () => {
                    const eventRes = await apiClient.createEvent(
                        testContract.id,
                        createEventPayload({ name: 'Ready to Cancel Event' }),
                        coordinatorHeaders
                    );
                    const event = getSuccessData<Event>(eventRes);

                    const shiftRes = await apiClient.createShift(
                        testContract.id,
                        event.id,
                        createShiftPayload({ role_name: 'Server' }),
                        coordinatorHeaders
                    );
                    const shift = getSuccessData<Shift>(shiftRes);

                    const staffRes = await apiClient.createStaffProfile(
                        testContract.id,
                        createStaffProfilePayload({ first_name: 'Jane', last_name: 'Smith' }),
                        coordinatorHeaders
                    );
                    const staff = getSuccessData<StaffProfile>(staffRes);

                    const assignmentRes = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(shift.id, staff.id),
                        accountManagerHeaders
                    );
                    const assignment = getSuccessData<Assignment>(assignmentRes);

                    await apiClient.acceptAssignment(testContract.id, assignment.id, staffMemberHeaders);
                    await apiClient.confirmAssignment(testContract.id, assignment.id, coordinatorHeaders);

                    const readyRes = await apiClient.updateEventStatus(
                        testContract.id,
                        event.id,
                        { status: EventStatus.READY_FOR_EXECUTION },
                        coordinatorHeaders
                    );
                    const readyEvent = handleApiResponse<Event>(readyRes, 200);
                    expect(readyEvent.status).toBe(EventStatus.READY_FOR_EXECUTION);

                    const cancelRes = await apiClient.updateEventStatus(
                        testContract.id,
                        event.id,
                        { status: EventStatus.CANCELLED },
                        coordinatorHeaders
                    );
                    const cancelledEvent = handleApiResponse<Event>(cancelRes, 200);

                    assertEvent(cancelledEvent);
                    expect(cancelledEvent.status).toBe(EventStatus.CANCELLED);

                    const getRes = await apiClient.getEvent(testContract.id, event.id, coordinatorHeaders);
                    const retrievedEvent = handleApiResponse<Event>(getRes, 200);
                    expect(retrievedEvent.status).toBe(EventStatus.CANCELLED);
                });
            });
        });

        describe('Transition: downgrade_to_planning (READY_FOR_EXECUTION -> PLANNING)', () => {
            describe('P2-EVENT-04.1: Event implicitly transitions to PLANNING when assignment is cancelled', () => {
                it('should transition event from READY_FOR_EXECUTION to PLANNING when an assignment is cancelled', async () => {
                    const eventRes = await apiClient.createEvent(
                        testContract.id,
                        createEventPayload({ name: 'Downgrade Event' }),
                        coordinatorHeaders
                    );
                    const event = getSuccessData<Event>(eventRes);

                    const shiftRes = await apiClient.createShift(
                        testContract.id,
                        event.id,
                        createShiftPayload({ role_name: 'Chef' }),
                        coordinatorHeaders
                    );
                    const shift = getSuccessData<Shift>(shiftRes);

                    const staffRes = await apiClient.createStaffProfile(
                        testContract.id,
                        createStaffProfilePayload({ first_name: 'Gordon', last_name: 'Ramsay' }),
                        coordinatorHeaders
                    );
                    const staff = getSuccessData<StaffProfile>(staffRes);

                    const assignmentRes = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(shift.id, staff.id),
                        accountManagerHeaders
                    );
                    const assignment = getSuccessData<Assignment>(assignmentRes);

                    await apiClient.acceptAssignment(testContract.id, assignment.id, staffMemberHeaders);
                    await apiClient.confirmAssignment(testContract.id, assignment.id, coordinatorHeaders);

                    const readyRes = await apiClient.updateEventStatus(
                        testContract.id,
                        event.id,
                        { status: EventStatus.READY_FOR_EXECUTION },
                        coordinatorHeaders
                    );
                    const readyEvent = handleApiResponse<Event>(readyRes, 200);
                    expect(readyEvent.status).toBe(EventStatus.READY_FOR_EXECUTION);

                    const cancelRes = await apiClient.cancelAssignment(
                        testContract.id,
                        assignment.id,
                        coordinatorHeaders
                    );
                    expect(cancelRes.status).toBe(200);

                    const getRes = await apiClient.getEvent(testContract.id, event.id, coordinatorHeaders);
                    const downgradedEvent = handleApiResponse<Event>(getRes, 200);
                    expect(downgradedEvent.status).toBe(EventStatus.PLANNING);
                });
            });

            describe('P2-EVENT-04.2: Event in PLANNING does not change when assignment is cancelled', () => {
                it('should keep event in PLANNING state when an assignment is cancelled', async () => {
                    const eventRes = await apiClient.createEvent(
                        testContract.id,
                        createEventPayload({ name: 'Planning Event' }),
                        coordinatorHeaders
                    );
                    const event = getSuccessData<Event>(eventRes);

                    const shift1Res = await apiClient.createShift(
                        testContract.id,
                        event.id,
                        createShiftPayload({ role_name: 'Shift 1' }),
                        coordinatorHeaders
                    );
                    const shift1 = getSuccessData<Shift>(shift1Res);

                    const shift2Res = await apiClient.createShift(
                        testContract.id,
                        event.id,
                        createShiftPayload({ role_name: 'Shift 2' }),
                        coordinatorHeaders
                    );
                    const shift2 = getSuccessData<Shift>(shift2Res);

                    const staffRes = await apiClient.createStaffProfile(
                        testContract.id,
                        createStaffProfilePayload({ first_name: 'Test', last_name: 'Staff' }),
                        coordinatorHeaders
                    );
                    const staff = getSuccessData<StaffProfile>(staffRes);

                    const assignment1Res = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(shift1.id, staff.id),
                        accountManagerHeaders
                    );
                    const assignment1 = getSuccessData<Assignment>(assignment1Res);

                    await apiClient.acceptAssignment(testContract.id, assignment1.id, staffMemberHeaders);
                    await apiClient.confirmAssignment(testContract.id, assignment1.id, coordinatorHeaders);

                    const eventBeforeCancelRes = await apiClient.getEvent(testContract.id, event.id, coordinatorHeaders);
                    const eventBeforeCancel = handleApiResponse<Event>(eventBeforeCancelRes, 200);
                    expect(eventBeforeCancel.status).toBe(EventStatus.PLANNING);

                    const cancelRes = await apiClient.cancelAssignment(
                        testContract.id,
                        assignment1.id,
                        coordinatorHeaders
                    );
                    expect(cancelRes.status).toBe(200);

                    const getRes = await apiClient.getEvent(testContract.id, event.id, coordinatorHeaders);
                    const eventAfterCancel = handleApiResponse<Event>(getRes, 200);
                    expect(eventAfterCancel.status).toBe(EventStatus.PLANNING);
                });
            });
        });
    });

    describe('Shift State Machine', () => {
        let testContract: StaffingContract;
        let testEvent: Event;

        beforeEach(async () => {
            const contractRes = await apiClient.createContract(
                createContractPayload({ client_name: 'Shift Test Contract' }),
                coordinatorHeaders
            );
            const contract = getSuccessData<StaffingContract>(contractRes);

            const activateRes = await apiClient.activateContract(contract.id, coordinatorHeaders);
            testContract = handleApiResponse<StaffingContract>(activateRes, 200);

            const eventRes = await apiClient.createEvent(
                testContract.id,
                createEventPayload({ name: 'Shift Test Event' }),
                coordinatorHeaders
            );
            testEvent = getSuccessData<Event>(eventRes);
        });

        describe('Transition: propose_assignment (OPEN -> PENDING_CONFIRMATION)', () => {
            describe('P2-SHIFT-01.1: Shift transitions to PENDING_CONFIRMATION when assignment is proposed', () => {
                it('should transition shift from OPEN to PENDING_CONFIRMATION when assignment is proposed', async () => {
                    const shiftRes = await apiClient.createShift(
                        testContract.id,
                        testEvent.id,
                        createShiftPayload({ role_name: 'Server' }),
                        coordinatorHeaders
                    );
                    const shift = getSuccessData<Shift>(shiftRes);
                    expect(shift.status).toBe(ShiftStatus.OPEN);

                    const staffRes = await apiClient.createStaffProfile(
                        testContract.id,
                        createStaffProfilePayload({ first_name: 'Alice', last_name: 'Anderson' }),
                        coordinatorHeaders
                    );
                    const staff = getSuccessData<StaffProfile>(staffRes);

                    const assignmentRes = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(shift.id, staff.id),
                        accountManagerHeaders
                    );
                    expect(assignmentRes.status).toBe(201);

                    const getShiftRes = await apiClient.getShift(
                        testContract.id,
                        testEvent.id,
                        shift.id,
                        coordinatorHeaders
                    );
                    const updatedShift = handleApiResponse<Shift>(getShiftRes, 200);
                    expect(updatedShift.status).toBe(ShiftStatus.PENDING_CONFIRMATION);
                });
            });

            describe('P2-SHIFT-01.2: Proposing assignment to FILLED shift fails', () => {
                it('should fail with conflict error when proposing assignment to a filled shift', async () => {
                    const shiftRes = await apiClient.createShift(
                        testContract.id,
                        testEvent.id,
                        createShiftPayload({ role_name: 'Manager' }),
                        coordinatorHeaders
                    );
                    const shift = getSuccessData<Shift>(shiftRes);

                    const staff1Res = await apiClient.createStaffProfile(
                        testContract.id,
                        createStaffProfilePayload({ first_name: 'Staff', last_name: 'One' }),
                        coordinatorHeaders
                    );
                    const staff1 = getSuccessData<StaffProfile>(staff1Res);

                    const staff2Res = await apiClient.createStaffProfile(
                        testContract.id,
                        createStaffProfilePayload({ first_name: 'Staff', last_name: 'Two' }),
                        coordinatorHeaders
                    );
                    const staff2 = getSuccessData<StaffProfile>(staff2Res);

                    const assignment1Res = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(shift.id, staff1.id),
                        accountManagerHeaders
                    );
                    const assignment1 = getSuccessData<Assignment>(assignment1Res);

                    await apiClient.acceptAssignment(testContract.id, assignment1.id, staffMemberHeaders);
                    await apiClient.confirmAssignment(testContract.id, assignment1.id, coordinatorHeaders);

                    const filledShiftRes = await apiClient.getShift(
                        testContract.id,
                        testEvent.id,
                        shift.id,
                        coordinatorHeaders
                    );
                    const filledShift = handleApiResponse<Shift>(filledShiftRes, 200);
                    expect(filledShift.status).toBe(ShiftStatus.FILLED);

                    const assignment2Res = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(shift.id, staff2.id),
                        accountManagerHeaders
                    );

                    validateErrorEnvelope(assignment2Res, {
                        expectedErrorId: ApiErrorId.ERR_SHIFT_NOT_OPEN
                    });

                    const finalShiftRes = await apiClient.getShift(
                        testContract.id,
                        testEvent.id,
                        shift.id,
                        coordinatorHeaders
                    );
                    const finalShift = handleApiResponse<Shift>(finalShiftRes, 200);
                    expect(finalShift.status).toBe(ShiftStatus.FILLED);
                });
            });
        });

        describe('Transition: reopen_shift (PENDING_CONFIRMATION -> OPEN)', () => {
            describe('P2-SHIFT-02.1: Shift transitions to OPEN when assignment is declined', () => {
                it('should transition shift from PENDING_CONFIRMATION to OPEN when assignment is declined', async () => {
                    const shiftRes = await apiClient.createShift(
                        testContract.id,
                        testEvent.id,
                        createShiftPayload({ role_name: 'Bartender' }),
                        coordinatorHeaders
                    );
                    const shift = getSuccessData<Shift>(shiftRes);

                    const staffRes = await apiClient.createStaffProfile(
                        testContract.id,
                        createStaffProfilePayload({ first_name: 'Bob', last_name: 'Brown' }),
                        coordinatorHeaders
                    );
                    const staff = getSuccessData<StaffProfile>(staffRes);

                    const assignmentRes = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(shift.id, staff.id),
                        accountManagerHeaders
                    );
                    const assignment = getSuccessData<Assignment>(assignmentRes);

                    const pendingShiftRes = await apiClient.getShift(
                        testContract.id,
                        testEvent.id,
                        shift.id,
                        coordinatorHeaders
                    );
                    const pendingShift = handleApiResponse<Shift>(pendingShiftRes, 200);
                    expect(pendingShift.status).toBe(ShiftStatus.PENDING_CONFIRMATION);

                    const declineRes = await apiClient.declineAssignment(
                        testContract.id,
                        assignment.id,
                        staffMemberHeaders
                    );
                    expect(declineRes.status).toBe(200);

                    const getShiftRes = await apiClient.getShift(
                        testContract.id,
                        testEvent.id,
                        shift.id,
                        coordinatorHeaders
                    );
                    const reopenedShift = handleApiResponse<Shift>(getShiftRes, 200);
                    expect(reopenedShift.status).toBe(ShiftStatus.OPEN);
                });
            });

            describe('P2-SHIFT-02.2: Invalid decline of non-existent assignment', () => {
                it('should return error when declining non-existent assignment', async () => {
                    const shiftRes = await apiClient.createShift(
                        testContract.id,
                        testEvent.id,
                        createShiftPayload({ role_name: 'Security' }),
                        coordinatorHeaders
                    );
                    const shift = getSuccessData<Shift>(shiftRes);
                    expect(shift.status).toBe(ShiftStatus.OPEN);

                    const NON_EXISTENT_UUID = '00000000-0000-0000-0000-000000000000';
                    const declineRes = await apiClient.declineAssignment(
                        testContract.id,
                        NON_EXISTENT_UUID,
                        staffMemberHeaders
                    );

                    validateErrorEnvelope(declineRes, {
                        expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND
                    });

                    const getShiftRes = await apiClient.getShift(
                        testContract.id,
                        testEvent.id,
                        shift.id,
                        coordinatorHeaders
                    );
                    const unchangedShift = handleApiResponse<Shift>(getShiftRes, 200);
                    expect(unchangedShift.status).toBe(ShiftStatus.OPEN);
                });
            });
        });

        describe('Transition: reopen_shift (FILLED -> OPEN)', () => {
            describe('P2-SHIFT-03.1: FILLED shift transitions to OPEN when assignment is cancelled', () => {
                it('should transition shift from FILLED to OPEN when confirmed assignment is cancelled', async () => {
                    const shiftRes = await apiClient.createShift(
                        testContract.id,
                        testEvent.id,
                        createShiftPayload({ role_name: 'Host' }),
                        coordinatorHeaders
                    );
                    const shift = getSuccessData<Shift>(shiftRes);

                    const staffRes = await apiClient.createStaffProfile(
                        testContract.id,
                        createStaffProfilePayload({ first_name: 'Charlie', last_name: 'Brown' }),
                        coordinatorHeaders
                    );
                    const staff = getSuccessData<StaffProfile>(staffRes);

                    const assignmentRes = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(shift.id, staff.id),
                        accountManagerHeaders
                    );
                    const assignment = getSuccessData<Assignment>(assignmentRes);

                    await apiClient.acceptAssignment(testContract.id, assignment.id, staffMemberHeaders);
                    await apiClient.confirmAssignment(testContract.id, assignment.id, coordinatorHeaders);

                    const filledShiftRes = await apiClient.getShift(
                        testContract.id,
                        testEvent.id,
                        shift.id,
                        coordinatorHeaders
                    );
                    const filledShift = handleApiResponse<Shift>(filledShiftRes, 200);
                    expect(filledShift.status).toBe(ShiftStatus.FILLED);

                    const cancelRes = await apiClient.cancelAssignment(
                        testContract.id,
                        assignment.id,
                        coordinatorHeaders
                    );
                    expect(cancelRes.status).toBe(200);

                    const getShiftRes = await apiClient.getShift(
                        testContract.id,
                        testEvent.id,
                        shift.id,
                        coordinatorHeaders
                    );
                    const reopenedShift = handleApiResponse<Shift>(getShiftRes, 200);
                    expect(reopenedShift.status).toBe(ShiftStatus.OPEN);
                });
            });

            describe('P2-SHIFT-03.2: CANCELLED shift is not reopened', () => {
                it('should not reopen cancelled shift when trying to cancel already-cancelled assignment', async () => {
                    const shiftRes = await apiClient.createShift(
                        testContract.id,
                        testEvent.id,
                        createShiftPayload({ role_name: 'Coordinator' }),
                        coordinatorHeaders
                    );
                    const shift = getSuccessData<Shift>(shiftRes);

                    const staffRes = await apiClient.createStaffProfile(
                        testContract.id,
                        createStaffProfilePayload({ first_name: 'David', last_name: 'Davis' }),
                        coordinatorHeaders
                    );
                    const staff = getSuccessData<StaffProfile>(staffRes);

                    const assignmentRes = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(shift.id, staff.id),
                        accountManagerHeaders
                    );
                    const assignment = getSuccessData<Assignment>(assignmentRes);

                    await apiClient.acceptAssignment(testContract.id, assignment.id, staffMemberHeaders);
                    await apiClient.confirmAssignment(testContract.id, assignment.id, coordinatorHeaders);

                    await apiClient.updateEventStatus(
                        testContract.id,
                        testEvent.id,
                        { status: EventStatus.CANCELLED },
                        coordinatorHeaders
                    );

                    const cancelledShiftRes = await apiClient.getShift(
                        testContract.id,
                        testEvent.id,
                        shift.id,
                        coordinatorHeaders
                    );
                    const cancelledShift = handleApiResponse<Shift>(cancelledShiftRes, 200);
                    expect(cancelledShift.status).toBe(ShiftStatus.CANCELLED);

                    const cancelRes = await apiClient.cancelAssignment(
                        testContract.id,
                        assignment.id,
                        coordinatorHeaders
                    );

                    validateErrorEnvelope(cancelRes, {
                        expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_CANCELLABLE
                    });

                    const finalShiftRes = await apiClient.getShift(
                        testContract.id,
                        testEvent.id,
                        shift.id,
                        coordinatorHeaders
                    );
                    const finalShift = handleApiResponse<Shift>(finalShiftRes, 200);
                    expect(finalShift.status).toBe(ShiftStatus.CANCELLED);
                });
            });
        });

        describe('Transition: confirm_assignment (PENDING_CONFIRMATION -> FILLED)', () => {
            describe('P2-SHIFT-04.1: PENDING_CONFIRMATION shift transitions to FILLED when assignment is confirmed', () => {
                it('should transition shift from PENDING_CONFIRMATION to FILLED when assignment is confirmed', async () => {
                    const shiftRes = await apiClient.createShift(
                        testContract.id,
                        testEvent.id,
                        createShiftPayload({ role_name: 'Waiter' }),
                        coordinatorHeaders
                    );
                    const shift = getSuccessData<Shift>(shiftRes);

                    const staffRes = await apiClient.createStaffProfile(
                        testContract.id,
                        createStaffProfilePayload({ first_name: 'Eve', last_name: 'Evans' }),
                        coordinatorHeaders
                    );
                    const staff = getSuccessData<StaffProfile>(staffRes);

                    const assignmentRes = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(shift.id, staff.id),
                        accountManagerHeaders
                    );
                    const assignment = getSuccessData<Assignment>(assignmentRes);

                    await apiClient.acceptAssignment(testContract.id, assignment.id, staffMemberHeaders);

                    const pendingShiftRes = await apiClient.getShift(
                        testContract.id,
                        testEvent.id,
                        shift.id,
                        coordinatorHeaders
                    );
                    const pendingShift = handleApiResponse<Shift>(pendingShiftRes, 200);
                    expect(pendingShift.status).toBe(ShiftStatus.PENDING_CONFIRMATION);

                    const confirmRes = await apiClient.confirmAssignment(
                        testContract.id,
                        assignment.id,
                        coordinatorHeaders
                    );
                    expect(confirmRes.status).toBe(200);

                    const getShiftRes = await apiClient.getShift(
                        testContract.id,
                        testEvent.id,
                        shift.id,
                        coordinatorHeaders
                    );
                    const filledShift = handleApiResponse<Shift>(getShiftRes, 200);
                    expect(filledShift.status).toBe(ShiftStatus.FILLED);
                });
            });

            describe('P2-SHIFT-04.2: Confirming assignment for OPEN shift fails', () => {
                it('should fail when trying to confirm a declined assignment', async () => {
                    const shiftRes = await apiClient.createShift(
                        testContract.id,
                        testEvent.id,
                        createShiftPayload({ role_name: 'Cook' }),
                        coordinatorHeaders
                    );
                    const shift = getSuccessData<Shift>(shiftRes);

                    const staffRes = await apiClient.createStaffProfile(
                        testContract.id,
                        createStaffProfilePayload({ first_name: 'Frank', last_name: 'Foster' }),
                        coordinatorHeaders
                    );
                    const staff = getSuccessData<StaffProfile>(staffRes);

                    const assignmentRes = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(shift.id, staff.id),
                        accountManagerHeaders
                    );
                    const assignment = getSuccessData<Assignment>(assignmentRes);

                    await apiClient.declineAssignment(testContract.id, assignment.id, staffMemberHeaders);

                    const openShiftRes = await apiClient.getShift(
                        testContract.id,
                        testEvent.id,
                        shift.id,
                        coordinatorHeaders
                    );
                    const openShift = handleApiResponse<Shift>(openShiftRes, 200);
                    expect(openShift.status).toBe(ShiftStatus.OPEN);

                    const confirmRes = await apiClient.confirmAssignment(
                        testContract.id,
                        assignment.id,
                        coordinatorHeaders
                    );

                    validateErrorEnvelope(confirmRes, {
                        expectedErrorId: ApiErrorId.ERR_ASSIGNMENT_NOT_ACCEPTED
                    });

                    const finalShiftRes = await apiClient.getShift(
                        testContract.id,
                        testEvent.id,
                        shift.id,
                        coordinatorHeaders
                    );
                    const finalShift = handleApiResponse<Shift>(finalShiftRes, 200);
                    expect(finalShift.status).toBe(ShiftStatus.OPEN);
                });
            });
        });

        describe('Transition: cancel (OPEN/PENDING_CONFIRMATION/FILLED -> CANCELLED)', () => {
            describe('P2-SHIFT-05.1: PENDING_CONFIRMATION shift transitions to CANCELLED when event is cancelled', () => {
                it('should transition shift from PENDING_CONFIRMATION to CANCELLED when parent event is cancelled', async () => {
                    const shiftRes = await apiClient.createShift(
                        testContract.id,
                        testEvent.id,
                        createShiftPayload({ role_name: 'Supervisor' }),
                        coordinatorHeaders
                    );
                    const shift = getSuccessData<Shift>(shiftRes);

                    const staffRes = await apiClient.createStaffProfile(
                        testContract.id,
                        createStaffProfilePayload({ first_name: 'Grace', last_name: 'Green' }),
                        coordinatorHeaders
                    );
                    const staff = getSuccessData<StaffProfile>(staffRes);

                    const assignmentRes = await apiClient.createAssignment(
                        testContract.id,
                        createAssignmentPayload(shift.id, staff.id),
                        accountManagerHeaders
                    );
                    const assignment = getSuccessData<Assignment>(assignmentRes);

                    const pendingShiftRes = await apiClient.getShift(
                        testContract.id,
                        testEvent.id,
                        shift.id,
                        coordinatorHeaders
                    );
                    const pendingShift = handleApiResponse<Shift>(pendingShiftRes, 200);
                    expect(pendingShift.status).toBe(ShiftStatus.PENDING_CONFIRMATION);

                    const cancelRes = await apiClient.updateEventStatus(
                        testContract.id,
                        testEvent.id,
                        { status: EventStatus.CANCELLED },
                        coordinatorHeaders
                    );
                    expect(cancelRes.status).toBe(200);

                    const getShiftRes = await apiClient.getShift(
                        testContract.id,
                        testEvent.id,
                        shift.id,
                        coordinatorHeaders
                    );
                    const cancelledShift = handleApiResponse<Shift>(getShiftRes, 200);
                    expect(cancelledShift.status).toBe(ShiftStatus.CANCELLED);

                    const getAssignmentRes = await apiClient.getAssignment(testContract.id, assignment.id, coordinatorHeaders);
                    const cancelledAssignment = handleApiResponse<Assignment>(getAssignmentRes, 200);
                    expect(cancelledAssignment.status).toBe(AssignmentStatus.CANCELLED);
                });
            });

            describe('P2-SHIFT-05.2: CANCELLED shift not affected by event re-cancellation', () => {
                it('should remain CANCELLED when parent event is cancelled again', async () => {
                    const shiftRes = await apiClient.createShift(
                        testContract.id,
                        testEvent.id,
                        createShiftPayload({ role_name: 'Assistant' }),
                        coordinatorHeaders
                    );
                    const shift = getSuccessData<Shift>(shiftRes);

                    await apiClient.updateEventStatus(
                        testContract.id,
                        testEvent.id,
                        { status: EventStatus.CANCELLED },
                        coordinatorHeaders
                    );

                    const cancelledShiftRes = await apiClient.getShift(
                        testContract.id,
                        testEvent.id,
                        shift.id,
                        coordinatorHeaders
                    );
                    const cancelledShift = handleApiResponse<Shift>(cancelledShiftRes, 200);
                    expect(cancelledShift.status).toBe(ShiftStatus.CANCELLED);

                    const secondCancelRes = await apiClient.updateEventStatus(
                        testContract.id,
                        testEvent.id,
                        { status: EventStatus.CANCELLED },
                        coordinatorHeaders
                    );

                    validateErrorEnvelope(secondCancelRes, {
                        expectedErrorId: ApiErrorId.ERR_ILLEGAL_EVENT_STATE_TRANSITION
                    });

                    const finalShiftRes = await apiClient.getShift(
                        testContract.id,
                        testEvent.id,
                        shift.id,
                        coordinatorHeaders
                    );
                    const finalShift = handleApiResponse<Shift>(finalShiftRes, 200);
                    expect(finalShift.status).toBe(ShiftStatus.CANCELLED);
                });
            });
        });
    });
});
