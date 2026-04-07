import {
  createProject,
  getProject,
  createWorkItem,
  getWorkItem,
  readyWorkItem,
  startWorkItem,
  createPermit,
  decidePermit,
  createInspection,
  submitInspection,
  createChangeOrder,
  getChangeOrder,
  approveChangeOrder,
  uniqueId,
  Project,
  WorkItem,
  Permit,
  Inspection,
  ChangeOrder,
} from './resources';

export interface FX_PROJECT_OPEN_120_Result {
  P: string;
  project: Project;
}

export interface FX_PROJECT_REVIEW_18_Result {
  P: string;
  project: Project;
}

export interface FX_ELECTRICAL_PERMIT_GRANTED_Result extends FX_PROJECT_OPEN_120_Result {
  PE: string;
}

export interface FX_PLUMBING_PERMIT_GRANTED_Result extends FX_PROJECT_OPEN_120_Result {
  PP: string;
}

export interface FX_STRUCTURAL_PERMIT_GRANTED_Result extends FX_PROJECT_OPEN_120_Result {
  PS: string;
}

export interface FX_CORE_PERMITS_GRANTED_Result extends FX_PROJECT_OPEN_120_Result {
  PE: string;
  PP: string;
  PS: string;
}

export interface FX_DRAFT_ELECTRICAL_ITEM_Result extends FX_ELECTRICAL_PERMIT_GRANTED_Result {
  W: string;
  EW: string;
}

export interface FX_READY_ELECTRICAL_ITEM_Result extends FX_DRAFT_ELECTRICAL_ITEM_Result {
  EW2: string;
}

export interface FX_INPROGRESS_ELECTRICAL_ITEM_Result extends FX_READY_ELECTRICAL_ITEM_Result {
  EW3: string;
}

export interface FX_DRAFT_GENERAL_ITEM_ZONE_A_Result extends FX_PROJECT_OPEN_120_Result {
  WG: string;
  EWG: string;
}

export interface FX_READY_GENERAL_ITEM_ZONE_A_Result extends FX_DRAFT_GENERAL_ITEM_ZONE_A_Result {
  EWG2: string;
}

export interface FX_INPROGRESS_GENERAL_ITEM_ZONE_A_Result extends FX_READY_GENERAL_ITEM_ZONE_A_Result {
  EWG3: string;
}

export interface FX_INPROGRESS_STRUCTURAL_CRITICAL_ZONE_B_Result extends FX_STRUCTURAL_PERMIT_GRANTED_Result {
  WS: string;
  EWS: string;
  EWS2: string;
  EWS3: string;
}

export interface FX_PLANNED_QUALITY_ON_ELECTRICAL_Result extends FX_INPROGRESS_ELECTRICAL_ITEM_Result {
  IQ: string;
}

export interface FX_FAILED_QUALITY_ON_ELECTRICAL_Result extends FX_PLANNED_QUALITY_ON_ELECTRICAL_Result {

}

export interface FX_PLANNED_SAFETY_ON_ELECTRICAL_Result extends FX_INPROGRESS_ELECTRICAL_ITEM_Result {
  IS: string;
}

export interface FX_FAILED_SAFETY_ON_ELECTRICAL_Result extends FX_PLANNED_SAFETY_ON_ELECTRICAL_Result {

}

export interface FX_APPROVED_SCOPE_CO_ON_READY_ELECTRICAL_Result extends FX_READY_ELECTRICAL_ITEM_Result {
  CO: string;
  ECO: string;
  ECO2: string;
}

export interface FX_APPROVED_BUDGETONLY_CO_ON_INPROGRESS_ELECTRICAL_Result extends FX_INPROGRESS_ELECTRICAL_ITEM_Result {
  COB: string;
  ECOB: string;
  ECOB2: string;
}

export interface FX_TWO_ACTIVE_QUALITY_FAILS_Result extends FX_CORE_PERMITS_GRANTED_Result {
  W1: string;
  EW1: string;
  EW1b: string;
  I1: string;
  W2: string;
  EW2: string;
  EW2b: string;
  I2: string;
}

export async function FX_PROJECT_OPEN_120(): Promise<FX_PROJECT_OPEN_120_Result> {
  const project = await createProject({
    name: `Alpha-${uniqueId()}`,
    labor_budget_hours: 120,
  }, 'MANAGER', `fx_p1_${uniqueId()}`);

  const fetched = await getProject(project.id);

  expect(fetched.posture).toBe('OPEN');
  expect(fetched.labor_reserved_hours).toBe(0);
  expect(fetched.labor_committed_hours).toBe(0);
  expect(fetched.labor_used_hours).toBe(0);
  expect(fetched.labor_available_hours).toBe(120);

  return {
    P: project.id,
    project: fetched,
  };
}

export async function FX_PROJECT_REVIEW_18(): Promise<FX_PROJECT_REVIEW_18_Result> {
  const project = await createProject({
    name: `Beta-${uniqueId()}`,
    labor_budget_hours: 18,
  }, 'MANAGER', `fx_p2_${uniqueId()}`);

  const fetched = await getProject(project.id);

  expect(fetched.posture).toBe('REVIEW');
  expect(fetched.labor_available_hours).toBe(18);

  return {
    P: project.id,
    project: fetched,
  };
}

export async function FX_ELECTRICAL_PERMIT_GRANTED(): Promise<FX_ELECTRICAL_PERMIT_GRANTED_Result> {
  const base = await FX_PROJECT_OPEN_120();

  const permit = await createPermit(
    base.P,
    { trade: 'ELECTRICAL' },
    'MANAGER',
    `fx_pe1_${uniqueId()}`
  );

  await decidePermit(
    base.P,
    permit.id,
    'GRANT',
    'MANAGER',
    `fx_ped1_${uniqueId()}`
  );

  const project = await getProject(base.P);
  const grantedPermit = project.permits.find(p => p.id === permit.id);
  expect(grantedPermit).toBeDefined();
  expect(grantedPermit!.trade).toBe('ELECTRICAL');
  expect(grantedPermit!.status).toBe('GRANTED');

  return {
    ...base,
    PE: permit.id,
  };
}

export async function FX_PLUMBING_PERMIT_GRANTED(): Promise<FX_PLUMBING_PERMIT_GRANTED_Result> {
  const base = await FX_PROJECT_OPEN_120();

  const permit = await createPermit(
    base.P,
    { trade: 'PLUMBING' },
    'MANAGER',
    `fx_pp1_${uniqueId()}`
  );

  await decidePermit(
    base.P,
    permit.id,
    'GRANT',
    'MANAGER',
    `fx_ppd1_${uniqueId()}`
  );

  const project = await getProject(base.P);
  const grantedPermit = project.permits.find(p => p.id === permit.id);
  expect(grantedPermit).toBeDefined();
  expect(grantedPermit!.trade).toBe('PLUMBING');
  expect(grantedPermit!.status).toBe('GRANTED');

  return {
    ...base,
    PP: permit.id,
  };
}

export async function FX_STRUCTURAL_PERMIT_GRANTED(): Promise<FX_STRUCTURAL_PERMIT_GRANTED_Result> {
  const base = await FX_PROJECT_OPEN_120();

  const permit = await createPermit(
    base.P,
    { trade: 'STRUCTURAL' },
    'MANAGER',
    `fx_ps1_${uniqueId()}`
  );

  await decidePermit(
    base.P,
    permit.id,
    'GRANT',
    'MANAGER',
    `fx_psd1_${uniqueId()}`
  );

  const project = await getProject(base.P);
  const grantedPermit = project.permits.find(p => p.id === permit.id);
  expect(grantedPermit).toBeDefined();
  expect(grantedPermit!.trade).toBe('STRUCTURAL');
  expect(grantedPermit!.status).toBe('GRANTED');

  return {
    ...base,
    PS: permit.id,
  };
}

export async function FX_CORE_PERMITS_GRANTED(): Promise<FX_CORE_PERMITS_GRANTED_Result> {
  const base = await FX_PROJECT_OPEN_120();

  const electricalPermit = await createPermit(
    base.P,
    { trade: 'ELECTRICAL' },
    'MANAGER',
    `fx_p3_${uniqueId()}`
  );
  await decidePermit(
    base.P,
    electricalPermit.id,
    'GRANT',
    'MANAGER',
    `fx_p4_${uniqueId()}`
  );

  const plumbingPermit = await createPermit(
    base.P,
    { trade: 'PLUMBING' },
    'MANAGER',
    `fx_p5_${uniqueId()}`
  );
  await decidePermit(
    base.P,
    plumbingPermit.id,
    'GRANT',
    'MANAGER',
    `fx_p6_${uniqueId()}`
  );

  const structuralPermit = await createPermit(
    base.P,
    { trade: 'STRUCTURAL' },
    'MANAGER',
    `fx_p7_${uniqueId()}`
  );
  await decidePermit(
    base.P,
    structuralPermit.id,
    'GRANT',
    'MANAGER',
    `fx_p8_${uniqueId()}`
  );

  return {
    ...base,
    PE: electricalPermit.id,
    PP: plumbingPermit.id,
    PS: structuralPermit.id,
  };
}

export async function FX_DRAFT_ELECTRICAL_ITEM(): Promise<FX_DRAFT_ELECTRICAL_ITEM_Result> {
  const base = await FX_ELECTRICAL_PERMIT_GRANTED();

  const workItem = await createWorkItem(
    base.P,
    {
      title: 'Panel',
      trade: 'ELECTRICAL',
      zone: 'ZONE_A',
      criticality: 'STANDARD',
      estimated_hours: 10,
    },
    'FOREMAN',
    `fx_we1_${uniqueId()}`
  );

  const fetched = await getWorkItem(base.P, workItem.id);

  return {
    ...base,
    W: workItem.id,
    EW: fetched.etag,
  };
}

export async function FX_READY_ELECTRICAL_ITEM(): Promise<FX_READY_ELECTRICAL_ITEM_Result> {
  const base = await FX_DRAFT_ELECTRICAL_ITEM();

  await readyWorkItem(
    base.P,
    base.W,
    base.EW,
    'FOREMAN',
    `fx_wr1_${uniqueId()}`
  );

  const fetched = await getWorkItem(base.P, base.W);

  return {
    ...base,
    EW2: fetched.etag,
  };
}

export async function FX_INPROGRESS_ELECTRICAL_ITEM(): Promise<FX_INPROGRESS_ELECTRICAL_ITEM_Result> {
  const base = await FX_READY_ELECTRICAL_ITEM();

  await startWorkItem(
    base.P,
    base.W,
    base.EW2,
    'FOREMAN',
    `fx_ws1_${uniqueId()}`
  );

  const fetched = await getWorkItem(base.P, base.W);

  return {
    ...base,
    EW3: fetched.etag,
  };
}

export async function FX_DRAFT_GENERAL_ITEM_ZONE_A(): Promise<FX_DRAFT_GENERAL_ITEM_ZONE_A_Result> {
  const base = await FX_PROJECT_OPEN_120();

  const workItem = await createWorkItem(
    base.P,
    {
      title: 'Cleanup',
      trade: 'GENERAL',
      zone: 'ZONE_A',
      criticality: 'STANDARD',
      estimated_hours: 4,
    },
    'FOREMAN',
    `fx_wg1_${uniqueId()}`
  );

  const fetched = await getWorkItem(base.P, workItem.id);

  return {
    ...base,
    WG: workItem.id,
    EWG: fetched.etag,
  };
}

export async function FX_READY_GENERAL_ITEM_ZONE_A(): Promise<FX_READY_GENERAL_ITEM_ZONE_A_Result> {
  const base = await FX_DRAFT_GENERAL_ITEM_ZONE_A();

  await readyWorkItem(
    base.P,
    base.WG,
    base.EWG,
    'FOREMAN',
    `fx_wgr1_${uniqueId()}`
  );

  const fetched = await getWorkItem(base.P, base.WG);

  return {
    ...base,
    EWG2: fetched.etag,
  };
}

export async function FX_INPROGRESS_GENERAL_ITEM_ZONE_A(): Promise<FX_INPROGRESS_GENERAL_ITEM_ZONE_A_Result> {
  const base = await FX_READY_GENERAL_ITEM_ZONE_A();

  await startWorkItem(
    base.P,
    base.WG,
    base.EWG2,
    'FOREMAN',
    `fx_wgs1_${uniqueId()}`
  );

  const fetched = await getWorkItem(base.P, base.WG);

  return {
    ...base,
    EWG3: fetched.etag,
  };
}

export async function FX_INPROGRESS_STRUCTURAL_CRITICAL_ZONE_B(): Promise<FX_INPROGRESS_STRUCTURAL_CRITICAL_ZONE_B_Result> {
  const base = await FX_STRUCTURAL_PERMIT_GRANTED();

  const workItem = await createWorkItem(
    base.P,
    {
      title: 'Beam',
      trade: 'STRUCTURAL',
      zone: 'ZONE_B',
      criticality: 'CRITICAL',
      estimated_hours: 30,
    },
    'FOREMAN',
    `fx_ws2_${uniqueId()}`
  );

  const fetched1 = await getWorkItem(base.P, workItem.id);

  await readyWorkItem(
    base.P,
    workItem.id,
    fetched1.etag,
    'FOREMAN',
    `fx_ws3_${uniqueId()}`
  );

  const fetched2 = await getWorkItem(base.P, workItem.id);

  await startWorkItem(
    base.P,
    workItem.id,
    fetched2.etag,
    'FOREMAN',
    `fx_ws4_${uniqueId()}`
  );

  const fetched3 = await getWorkItem(base.P, workItem.id);

  return {
    ...base,
    WS: workItem.id,
    EWS: fetched1.etag,
    EWS2: fetched2.etag,
    EWS3: fetched3.etag,
  };
}

export async function FX_PLANNED_QUALITY_ON_ELECTRICAL(): Promise<FX_PLANNED_QUALITY_ON_ELECTRICAL_Result> {
  const base = await FX_INPROGRESS_ELECTRICAL_ITEM();

  const inspection = await createInspection(
    base.P,
    {
      work_item_id: base.W,
      kind: 'QUALITY',
    },
    'INSPECTOR',
    `fx_iq1_${uniqueId()}`
  );

  return {
    ...base,
    IQ: inspection.id,
  };
}

export async function FX_FAILED_QUALITY_ON_ELECTRICAL(): Promise<FX_FAILED_QUALITY_ON_ELECTRICAL_Result> {
  const base = await FX_PLANNED_QUALITY_ON_ELECTRICAL();

  await submitInspection(
    base.P,
    base.IQ,
    'FAILED',
    'INSPECTOR',
    `fx_iq2_${uniqueId()}`
  );

  const workItem = await getWorkItem(base.P, base.W);
  expect(workItem.latest_quality_status).toBe('FAILED');

  return base;
}

export async function FX_PLANNED_SAFETY_ON_ELECTRICAL(): Promise<FX_PLANNED_SAFETY_ON_ELECTRICAL_Result> {
  const base = await FX_INPROGRESS_ELECTRICAL_ITEM();

  const inspection = await createInspection(
    base.P,
    {
      work_item_id: base.W,
      kind: 'SAFETY',
    },
    'INSPECTOR',
    `fx_is1_${uniqueId()}`
  );

  return {
    ...base,
    IS: inspection.id,
  };
}

export async function FX_FAILED_SAFETY_ON_ELECTRICAL(): Promise<FX_FAILED_SAFETY_ON_ELECTRICAL_Result> {
  const base = await FX_PLANNED_SAFETY_ON_ELECTRICAL();

  await submitInspection(
    base.P,
    base.IS,
    'FAILED',
    'INSPECTOR',
    `fx_is2_${uniqueId()}`
  );

  const project = await getProject(base.P);
  expect(project.posture).toBe('STOP_WORK');

  return base;
}

export async function FX_APPROVED_SCOPE_CO_ON_READY_ELECTRICAL(): Promise<FX_APPROVED_SCOPE_CO_ON_READY_ELECTRICAL_Result> {
  const base = await FX_READY_ELECTRICAL_ITEM();

  const changeOrder = await createChangeOrder(
    base.P,
    {
      work_item_id: base.W,
      summary: 'Shift zone + re-estimate',
      new_zone: 'ZONE_B',
      new_estimated_hours: 12,
    },
    'FOREMAN',
    `fx_co1_${uniqueId()}`
  );

  const fetched1 = await getChangeOrder(base.P, changeOrder.id);

  await approveChangeOrder(
    base.P,
    changeOrder.id,
    fetched1.etag,
    'MANAGER',
    `fx_co2_${uniqueId()}`
  );

  const fetched2 = await getChangeOrder(base.P, changeOrder.id);

  return {
    ...base,
    CO: changeOrder.id,
    ECO: fetched1.etag,
    ECO2: fetched2.etag,
  };
}

export async function FX_APPROVED_BUDGETONLY_CO_ON_INPROGRESS_ELECTRICAL(): Promise<FX_APPROVED_BUDGETONLY_CO_ON_INPROGRESS_ELECTRICAL_Result> {
  const base = await FX_INPROGRESS_ELECTRICAL_ITEM();

  const changeOrder = await createChangeOrder(
    base.P,
    {
      work_item_id: base.W,
      summary: 'Labor add',
      labor_budget_hours_delta: 20,
    },
    'FOREMAN',
    `fx_cob1_${uniqueId()}`
  );

  const fetched1 = await getChangeOrder(base.P, changeOrder.id);

  await approveChangeOrder(
    base.P,
    changeOrder.id,
    fetched1.etag,
    'MANAGER',
    `fx_cob2_${uniqueId()}`
  );

  const fetched2 = await getChangeOrder(base.P, changeOrder.id);

  return {
    ...base,
    COB: changeOrder.id,
    ECOB: fetched1.etag,
    ECOB2: fetched2.etag,
  };
}

export interface FX_ZONE_A_OCCUPIED_BY_ELECTRICAL_Result extends FX_ELECTRICAL_PERMIT_GRANTED_Result {
  W: string;
  EW: string;
  EW2: string;
  EW3: string;
}

export async function FX_ZONE_A_OCCUPIED_BY_ELECTRICAL(): Promise<FX_ZONE_A_OCCUPIED_BY_ELECTRICAL_Result> {
  const base = await FX_ELECTRICAL_PERMIT_GRANTED();

  const workItem = await createWorkItem(
    base.P,
    {
      title: 'ZoneAOccupant',
      trade: 'ELECTRICAL',
      zone: 'ZONE_A',
      criticality: 'STANDARD',
      estimated_hours: 10,
    },
    'FOREMAN',
    `fx_zo1_${uniqueId()}`
  );

  const fetched1 = await getWorkItem(base.P, workItem.id);

  await readyWorkItem(
    base.P,
    workItem.id,
    fetched1.etag,
    'FOREMAN',
    `fx_zo2_${uniqueId()}`
  );

  const fetched2 = await getWorkItem(base.P, workItem.id);

  await startWorkItem(
    base.P,
    workItem.id,
    fetched2.etag,
    'FOREMAN',
    `fx_zo3_${uniqueId()}`
  );

  const fetched3 = await getWorkItem(base.P, workItem.id);

  return {
    ...base,
    W: workItem.id,
    EW: fetched1.etag,
    EW2: fetched2.etag,
    EW3: fetched3.etag,
  };
}

export async function FX_TWO_ACTIVE_QUALITY_FAILS(): Promise<FX_TWO_ACTIVE_QUALITY_FAILS_Result> {
  const base = await FX_CORE_PERMITS_GRANTED();

  const workItem1 = await createWorkItem(
    base.P,
    {
      title: 'Rough-in',
      trade: 'ELECTRICAL',
      zone: 'ZONE_A',
      criticality: 'STANDARD',
      estimated_hours: 10,
    },
    'FOREMAN',
    `fx_w2_${uniqueId()}`
  );

  const fetched1 = await getWorkItem(base.P, workItem1.id);

  await readyWorkItem(
    base.P,
    workItem1.id,
    fetched1.etag,
    'FOREMAN',
    `fx_w3_${uniqueId()}`
  );

  const fetched1b = await getWorkItem(base.P, workItem1.id);

  await startWorkItem(
    base.P,
    workItem1.id,
    fetched1b.etag,
    'FOREMAN',
    `fx_w4_${uniqueId()}`
  );

  const inspection1 = await createInspection(
    base.P,
    {
      work_item_id: workItem1.id,
      kind: 'QUALITY',
    },
    'INSPECTOR',
    `fx_w5_${uniqueId()}`
  );

  await submitInspection(
    base.P,
    inspection1.id,
    'FAILED',
    'INSPECTOR',
    `fx_w6_${uniqueId()}`
  );

  const workItem2 = await createWorkItem(
    base.P,
    {
      title: 'Stack',
      trade: 'PLUMBING',
      zone: 'ZONE_B',
      criticality: 'STANDARD',
      estimated_hours: 10,
    },
    'FOREMAN',
    `fx_w7_${uniqueId()}`
  );

  const fetched2 = await getWorkItem(base.P, workItem2.id);

  await readyWorkItem(
    base.P,
    workItem2.id,
    fetched2.etag,
    'FOREMAN',
    `fx_w8_${uniqueId()}`
  );

  const fetched2b = await getWorkItem(base.P, workItem2.id);

  await startWorkItem(
    base.P,
    workItem2.id,
    fetched2b.etag,
    'FOREMAN',
    `fx_w9_${uniqueId()}`
  );

  const inspection2 = await createInspection(
    base.P,
    {
      work_item_id: workItem2.id,
      kind: 'QUALITY',
    },
    'INSPECTOR',
    `fx_w10_${uniqueId()}`
  );

  await submitInspection(
    base.P,
    inspection2.id,
    'FAILED',
    'INSPECTOR',
    `fx_w11_${uniqueId()}`
  );

  const project = await getProject(base.P);
  expect(project.posture).toBe('REVIEW');

  return {
    ...base,
    W1: workItem1.id,
    EW1: fetched1.etag,
    EW1b: fetched1b.etag,
    I1: inspection1.id,
    W2: workItem2.id,
    EW2: fetched2.etag,
    EW2b: fetched2b.etag,
    I2: inspection2.id,
  };
}
